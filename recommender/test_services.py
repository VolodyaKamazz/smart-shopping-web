from decimal import Decimal

from django.test import SimpleTestCase

from .services import WEIGHTS, bayesian_rating, build_explanation, rank


def make(offer_id, price, delivery=0, days=(1, 1), rating=4.5, count=100, shop=None):
    return {
        "id": offer_id, "shop": shop or f"Магазин {offer_id}", "title": "Samsung Galaxy A55", "price": price,
        "delivery_price": delivery, "min_days": days[0] if days else None, "max_days": days[1] if days else None,
        "rating": rating, "rating_count": count,
    }


OFFERS = [
    make(1, 30000, 0, (1, 1), 4.7, 200),
    make(2, 28000, 500, (3, 4), 4.5, 100),
    make(3, 26000, 900, (6, 8), 4.6, 150),
]


class WeightsTests(SimpleTestCase):
    def test_each_weight_set_sums_to_one(self):
        for name, weights in WEIGHTS.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_three_criteria(self):
        self.assertEqual(set(WEIGHTS), {"balanced", "price", "speed"})


class RankTests(SimpleTestCase):
    def test_price_criterion_prefers_cheapest_total(self):
        ranked = rank(OFFERS, {"priority": "price"})
        self.assertEqual(ranked[0]["id"], 3)
        self.assertEqual(ranked[0]["total_price"], Decimal("26900"))

    def test_speed_criterion_prefers_fastest(self):
        self.assertEqual(rank(OFFERS, {"priority": "speed"})[0]["id"], 1)

    def test_criterion_changes_recommendation(self):
        winners = {p: rank(OFFERS, {"priority": p})[0]["id"] for p in ("price", "speed", "balanced")}
        self.assertNotEqual(winners["price"], winners["speed"])

    def test_balanced_prefers_middle_option(self):
        offers = [make(1, 30000, 0, (1, 1)), make(2, 25000, 0, (4, 4)), make(3, 27000, 0, (2, 2))]
        self.assertEqual(rank(offers, {"priority": "balanced"})[0]["id"], 3)

    def test_unknown_priority_falls_back_to_balanced(self):
        ranked = rank(OFFERS, {"priority": "nonsense"})
        self.assertEqual(ranked[0]["priority"], "balanced")
        self.assertEqual([o["id"] for o in ranked], [o["id"] for o in rank(OFFERS, {"priority": "balanced"})])

    def test_missing_profile(self):
        self.assertEqual(len(rank(OFFERS, None)), 3)

    def test_ranks_start_from_one_and_only_first_recommended(self):
        ranked = rank(OFFERS, {"priority": "balanced"})
        self.assertEqual([o["rank"] for o in ranked], [1, 2, 3])
        self.assertEqual([o["is_recommended"] for o in ranked], [True, False, False])

    def test_scores_are_sorted_descending(self):
        scores = [o["score"] for o in rank(OFFERS, {"priority": "balanced"})]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_breakdown_contains_components_and_weights(self):
        breakdown = rank(OFFERS, {"priority": "speed"})[0]["breakdown"]
        self.assertEqual(set(breakdown), {"price", "speed", "reliability", "weights"})
        self.assertEqual(breakdown["weights"], WEIGHTS["speed"])

    def test_budget_is_a_hard_condition(self):
        ranked = rank(OFFERS, {"priority": "balanced", "budget_max": 28500})
        self.assertEqual([o["id"] for o in ranked if o["total_price"] > 28500], [])
        self.assertEqual({o["id"] for o in ranked}, {2, 3})

    def test_budget_excludes_everything(self):
        self.assertEqual(rank(OFFERS, {"priority": "balanced", "budget_max": 1000}), [])

    def test_empty_offers(self):
        self.assertEqual(rank([], {"priority": "price"}), [])

    def test_single_offer(self):
        ranked = rank([make(1, 1000)], {"priority": "speed"})
        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0]["is_recommended"])

    def test_unknown_delivery_does_not_win_by_default(self):
        offers = [make(1, 30000, 0, (1, 1)), make(2, 30000, None, None)]
        ranked = rank(offers, {"priority": "speed"})
        self.assertEqual(ranked[0]["id"], 1)

    def test_all_delivery_unknown_leaves_price_decisive(self):
        offers = [make(1, 30000, None, None), make(2, 20000, None, None)]
        self.assertEqual(rank(offers, {"priority": "price"})[0]["id"], 2)

    def test_equal_offers_are_ordered_by_total_then_id(self):
        offers = [make(2, 1000), make(1, 1000)]
        self.assertEqual([o["id"] for o in rank(offers, {"priority": "price"})], [1, 2])

    def test_decimal_prices_are_supported(self):
        offers = [make(1, Decimal("999.50"), Decimal("100")), make(2, Decimal("1200"), Decimal("0"))]
        ranked = rank(offers, {"priority": "price"})
        self.assertEqual(ranked[0]["total_price"], Decimal("1099.50"))

    def test_original_offers_are_not_mutated(self):
        offers = [make(1, 100), make(2, 200)]
        rank(offers, {"priority": "price"})
        self.assertNotIn("score", offers[0])


class BayesianRatingTests(SimpleTestCase):
    def test_few_votes_are_pulled_towards_prior(self):
        self.assertLess(bayesian_rating(5.0, 1, 4.0), 4.1)

    def test_many_votes_keep_rating(self):
        self.assertGreater(bayesian_rating(5.0, 2000, 4.0), 4.9)

    def test_missing_rating_gives_prior(self):
        self.assertEqual(bayesian_rating(None, 0, 4.2), 4.2)

    def test_reliable_shop_beats_unproven_with_same_price_and_speed(self):
        offers = [make(1, 1000, rating=5.0, count=1), make(2, 1000, rating=4.8, count=500),
                  make(3, 1000, rating=3.0, count=100)]
        ranked = rank(offers, {"priority": "balanced"})
        self.assertEqual([o["id"] for o in ranked], [2, 1, 3])


class ExplanationTests(SimpleTestCase):
    def explain(self, priority):
        ranked = rank(OFFERS, {"priority": priority})
        return build_explanation(ranked[0], ranked[1:])

    def test_text_contains_shop_prices_and_days(self):
        text, facts = self.explain("speed")
        self.assertIn("Магазин 1", text)
        self.assertIn("30\u00a0000", text)
        self.assertIn("доставка бесплатная", text)
        self.assertIn("Срок доставки: 1 дн.", text)
        self.assertEqual(facts["delivery_days"], "1 дн.")

    def test_reason_depends_on_criterion(self):
        self.assertIn("самая быстрая доставка", self.explain("speed")[0])
        self.assertIn("самая низкая итоговая стоимость", self.explain("price")[0])
        offers = [make(1, 30000, 0, (1, 1)), make(2, 25000, 0, (4, 4)), make(3, 27000, 0, (2, 2))]
        ranked = rank(offers, {"priority": "balanced"})
        self.assertIn("лучшее сочетание", build_explanation(ranked[0], ranked[1:])[0])

    def test_speed_reason_is_not_overstated(self):
        offers = [make(1, 100000, 0, (1, 1), 3.0, 100), make(2, 10000, 0, (2, 2), 5.0, 100),
                  make(3, 50000, 0, (10, 10), 4.0, 100)]
        ranked = rank(offers, {"priority": "speed"})
        self.assertEqual(ranked[0]["id"], 2)
        text, _ = build_explanation(ranked[0], ranked[1:])
        self.assertNotIn("самая быстрая доставка", text)
        self.assertIn("учтён приоритет скорости", text)

    def test_price_reason_is_not_overstated(self):
        offers = [make(1, 1000, 0, (30, 30), 1.0, 1000), make(2, 1010, 0, (1, 1), 5.0, 1000),
                  make(3, 2000, 0, (15, 15), 3.0, 1000)]
        ranked = rank(offers, {"priority": "price"})
        self.assertEqual(ranked[0]["id"], 2)
        text, _ = build_explanation(ranked[0], ranked[1:])
        self.assertNotIn("самая низкая итоговая стоимость", text)
        self.assertIn("учтён приоритет цены", text)

    def test_speed_reason_when_delivery_unknown(self):
        ranked = rank([make(1, 1000, None, None), make(2, 2000, None, None)], {"priority": "speed"})
        text, _ = build_explanation(ranked[0], ranked[1:])
        self.assertIn("учтён приоритет скорости", text)

    def test_saving_against_average_of_others(self):
        text, facts = self.explain("price")
        self.assertEqual(facts["total_price"], 26900.0)
        self.assertEqual(facts["saving"], 2350.0)
        self.assertIn("дешевле, чем в среднем", text)

    def test_days_gain(self):
        text, facts = self.explain("speed")
        self.assertGreater(facts["days_gain"], 0)
        self.assertIn("Доставка быстрее в среднем", text)

    def test_no_saving_sentence_when_not_cheaper(self):
        text, facts = self.explain("speed")
        self.assertEqual(facts["saving"], 0.0)
        self.assertNotIn("дешевле", text)

    def test_facts_are_json_serializable(self):
        import json
        json.dumps(self.explain("balanced")[1])

    def test_single_offer_text(self):
        ranked = rank([make(1, 5000, 300, (2, 3))], {"priority": "price"})
        text, facts = build_explanation(ranked[0], [])
        self.assertIn("единственное подходящее предложение", text)
        self.assertEqual(facts["offers_compared"], 1)

    def test_unknown_delivery_wording(self):
        ranked = rank([make(1, 5000, None, None)], {"priority": "price"})
        text, _ = build_explanation(ranked[0], [])
        self.assertIn("стоимость доставки уточняется", text)
        self.assertNotIn("Срок доставки", text)

    def test_rating_wording(self):
        ranked = rank([make(1, 5000, 0, (1, 1), 4.7, 1)], {"priority": "price"})
        self.assertIn("Рейтинг магазина: 4,7 (1 оценка).", build_explanation(ranked[0], [])[0])
        ranked = rank([make(1, 5000, 0, (1, 1), 4.7, 3)], {"priority": "price"})
        self.assertIn("(3 оценки)", build_explanation(ranked[0], [])[0])
        ranked = rank([make(1, 5000, 0, (1, 1), 4.7, 25)], {"priority": "price"})
        self.assertIn("(25 оценок)", build_explanation(ranked[0], [])[0])

    def test_no_rating(self):
        ranked = rank([make(1, 5000, 0, (1, 1), None, 0)], {"priority": "price"})
        text, facts = build_explanation(ranked[0], [])
        self.assertNotIn("Рейтинг", text)
        self.assertIsNone(facts["rating"])
