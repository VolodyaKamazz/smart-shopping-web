from decimal import Decimal

from django.test import SimpleTestCase

from recommender.services import WEIGHTS, Candidate, bayesian_rating, fill_unknown, normalize, prior_rating, rank


def candidate(offer_id, price="10000", delivery_price="0", days=3, shop_id=None, **fields):
    values = {"offer_id": offer_id, "shop_id": shop_id or offer_id, "price": Decimal(price),
              "delivery_price": None if delivery_price is None else Decimal(delivery_price),
              "delivery_days": days, "in_stock": True, "is_active": True, "rating": Decimal("4.5"),
              "rating_count": 1000, "warranty_months": 12, "return_days": 7}
    values.update(fields)
    return Candidate(**values)


def order(ranked):
    return [item.offer_id for item in ranked]


class WeightsTests(SimpleTestCase):
    def test_every_set_sums_to_one(self):
        for name, weights in WEIGHTS.items():
            self.assertAlmostEqual(sum(weights.values()), 1.0, msg=name)


class BayesianRatingTests(SimpleTestCase):
    def test_formula(self):
        self.assertAlmostEqual(bayesian_rating(Decimal("4.8"), 150, 4.0), (150 * 4.8 + 50 * 4.0) / 200)

    def test_single_perfect_vote_does_not_beat_established_shop(self):
        newcomer = bayesian_rating(Decimal("5"), 1, 4.5)
        established = bayesian_rating(Decimal("4.8"), 300, 4.5)
        self.assertLess(newcomer, established)

    def test_no_votes_or_rating_gives_prior(self):
        self.assertEqual(bayesian_rating(None, 100, 4.2), 4.2)
        self.assertEqual(bayesian_rating(Decimal("5"), 0, 4.2), 4.2)


class HelpersTests(SimpleTestCase):
    def test_normalize_lower_is_better(self):
        self.assertEqual(normalize([100, 200, 150], higher_is_better=False), [1.0, 0.0, 0.5])

    def test_unknown_values_take_worst_known(self):
        self.assertEqual(fill_unknown([100, None, 300]), [100, 300, 300])
        self.assertEqual(fill_unknown([None, None]), [0, 0])

    def test_prior_rating_is_average_over_shops_not_offers(self):
        offers = [candidate(1, shop_id=1, rating=Decimal("5")), candidate(2, shop_id=1, rating=Decimal("5")),
                  candidate(3, shop_id=2, rating=Decimal("3")), candidate(4, shop_id=3, rating=None)]
        self.assertEqual(prior_rating(offers, {}), 4.0)


class HardConditionsTests(SimpleTestCase):

    def test_out_of_stock_and_inactive_are_dropped(self):
        offers = [candidate(1, in_stock=False), candidate(2, is_active=False), candidate(3)]
        self.assertEqual(order(rank(offers, {})), [3])

    def test_budget_counts_known_delivery(self):
        offers = [candidate(1, "9500", "600"), candidate(2, "9500", "400")]
        self.assertEqual(order(rank(offers, {"budget_max": Decimal("10000")})), [2])

    def test_unknown_delivery_counts_as_zero_for_budget(self):
        self.assertEqual(order(rank([candidate(1, "9900", None, None)], {"budget_max": Decimal("10000")})), [1])


class PriorityTests(SimpleTestCase):
    def setUp(self):
        self.cheap_slow = candidate(1, "10000", "0", days=10)
        self.pricey_fast = candidate(2, "11000", "0", days=1)
        self.offers = [self.cheap_slow, self.pricey_fast]

    def test_price_priority_prefers_cheap(self):
        self.assertEqual(order(rank(self.offers, {"priority": "price"})), [1, 2])

    def test_speed_priority_prefers_fast(self):
        self.assertEqual(order(rank(self.offers, {"priority": "speed"})), [2, 1])

    def test_missing_or_unknown_priority_is_balanced(self):
        expected = rank(self.offers, {"priority": "balanced"})
        self.assertEqual(rank(self.offers, {}), expected)
        self.assertEqual(rank(self.offers, {"priority": "turbo"}), expected)


class CriteriaTests(SimpleTestCase):
    def test_established_shop_beats_newcomer_with_perfect_rating_otherwise_equal(self):
        newcomer = candidate(1, rating=Decimal("5"), rating_count=1)
        established = candidate(2, rating=Decimal("4.8"), rating_count=300)
        profile = {"prior_rating": Decimal("4.5")}
        self.assertEqual(order(rank([newcomer, established], profile)), [2, 1])

    def test_better_terms_win_when_everything_else_is_equal(self):
        weak = candidate(1, warranty_months=3, return_days=7)
        strong = candidate(2, warranty_months=24, return_days=14)
        self.assertEqual(order(rank([weak, strong], {})), [2, 1])

    def test_unknown_delivery_does_not_win_against_known(self):
        known = candidate(1, "10000", "500", days=5)
        unknown = candidate(2, "10000", None, None)
        self.assertEqual(order(rank([unknown, known], {"priority": "speed"})), [1, 2])

    def test_unknown_delivery_takes_worst_known_values(self):
        offers = [candidate(1, "10000", "500", days=5), candidate(2, "10000", None, None),
                  candidate(3, "10000", "100", days=2)]
        ranked = {item.offer_id: item for item in rank(offers, {})}
        self.assertEqual(ranked[2].breakdown["price"], ranked[1].breakdown["price"])
        self.assertEqual(ranked[2].breakdown["delivery"], ranked[1].breakdown["delivery"])


class RankOutputTests(SimpleTestCase):
    def setUp(self):
        self.offers = [candidate(1, "10000", "300", 4), candidate(2, "9000", "800", 2, rating=Decimal("4.1")),
                       candidate(3, "9500", "0", 6, rating_count=5)]

    def test_ranks_are_consecutive_and_scores_descend(self):
        ranked = rank(self.offers, {})
        self.assertEqual([item.rank for item in ranked], [1, 2, 3])
        scores = [item.score for item in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_only_first_is_recommended(self):
        self.assertEqual([item.is_recommended for item in rank(self.offers, {})], [True, False, False])

    def test_breakdown_sums_to_score(self):
        for item in rank(self.offers, {}):
            self.assertAlmostEqual(sum(item.breakdown.values()), item.score, places=3)
            self.assertEqual(set(item.breakdown), set(WEIGHTS["balanced"]))

    def test_does_not_depend_on_input_order(self):
        forward = rank(self.offers, {})
        backward = rank(list(reversed(self.offers)), {})
        self.assertEqual(forward, backward)

    def test_float_noise_does_not_override_tie_break(self):
        offers = [candidate(1, "2000", "200", 2, shop_id=2, rating=None, return_days=None),
                  candidate(2, "3000", "0", 1, shop_id=1, rating=None),
                  candidate(3, "1000", "200", 2, shop_id=1, rating=None),
                  candidate(4, "3000", None, None, shop_id=2, rating=None, return_days=None),
                  candidate(5, "2000", "200", 3, shop_id=1, rating=None)]
        self.assertEqual(order(rank(offers, {"priority": "speed"})), [3, 2, 1, 5, 4])
