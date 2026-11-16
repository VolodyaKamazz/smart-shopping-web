from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from catalog.models import Offer, Shop
from delivery.testing import make_city, make_rule, make_shop
from search.models import SearchRequest
from search.ranking import build_candidate, build_profile, rank_and_save


class RankingBase(TestCase):
    def setUp(self):
        self.moscow = make_city("Москва", 1)
        self.tomsk = make_city("Томск", 7)
        self.fast = Shop.objects.create(name="Быстрый", rating=Decimal("4.5"), rating_count=1000, return_days=14,
                                        warranty_months=24)
        self.cheap = Shop.objects.create(name="Дешёвый", rating=Decimal("4.5"), rating_count=1000, return_days=14,
                                         warranty_months=24)
        make_rule(self.fast, "500", 1, 2)
        make_rule(self.cheap, "100", 6, 10)

    def offer(self, shop, price, external_id=None, **fields):
        external_id = external_id or f"{shop.name}-{price}"
        return Offer.objects.create(shop=shop, external_id=external_id, url="https://shop.example/p",
                                    title_raw="Товар", price=Decimal(price), **fields)

    def search(self, user=None, city=None):
        return SearchRequest.objects.create(raw_query="товар", session_key="s", user=user, city=city)

    def user(self, **fields):
        return User.objects.create_user("u", "u@example.com", "Str0ng-pass-123", **fields)

    def saved(self, search):
        return list(search.results.select_related("offer__shop").order_by("rank"))


class RankAndSaveTests(RankingBase):
    def test_delivery_and_scores_are_saved_with_each_result(self):
        offers = [self.offer(self.fast, "10000"), self.offer(self.cheap, "10000")]
        search = self.search(city=self.tomsk)
        self.assertEqual(rank_and_save(search, offers), 2)
        first, second = self.saved(search)
        self.assertEqual(first.offer.shop, self.cheap)
        self.assertEqual((first.delivery_price, first.delivery_min_days, first.delivery_max_days,
                          first.delivery_source, first.delivery_method),
                         (Decimal("100"), 6, 10, "shop", "courier"))
        self.assertEqual(first.total_price, Decimal("10100"))
        self.assertEqual(first.item_price, Decimal("10000"))
        self.assertEqual(set(first.breakdown), {"price", "delivery", "reliability", "terms", "preference"})
        self.assertGreater(first.score, second.score)
        self.assertEqual([first.is_recommended, second.is_recommended], [True, False])

    def test_user_priority_changes_the_winner(self):
        offers = [self.offer(self.fast, "10000"), self.offer(self.cheap, "10000")]
        speed_search = self.search(user=self.user(delivery_priority="speed"), city=self.tomsk)
        rank_and_save(speed_search, offers)
        self.assertEqual(self.saved(speed_search)[0].offer.shop, self.fast)

    def test_user_budget_drops_offers_with_delivery_above_limit(self):
        offers = [self.offer(self.fast, "9800"), self.offer(self.cheap, "9800")]
        search = self.search(user=self.user(budget_max=Decimal("10000")), city=self.tomsk)
        rank_and_save(search, offers)
        self.assertEqual([r.offer.shop for r in self.saved(search)], [self.cheap])

    def test_unknown_delivery_is_saved_without_numbers(self):
        shop = make_shop("Без условий")
        search = self.search(city=self.tomsk)
        rank_and_save(search, [self.offer(shop, "5000")])
        result = self.saved(search)[0]
        self.assertEqual((result.delivery_price, result.delivery_min_days, result.delivery_max_days,
                          result.delivery_source, result.delivery_method), (None, None, None, "unknown", ""))
        self.assertEqual(result.total_price, Decimal("5000"))

    def test_rerun_replaces_results(self):
        offers = [self.offer(self.fast, "100"), self.offer(self.cheap, "200")]
        search = self.search(city=self.tomsk)
        rank_and_save(search, offers)
        rank_and_save(search, offers)
        self.assertEqual(search.results.count(), 2)

    def test_empty_offers_clear_old_results(self):
        offers = [self.offer(self.fast, "100")]
        search = self.search(city=self.tomsk)
        rank_and_save(search, offers)
        self.assertEqual(rank_and_save(search, []), 0)
        self.assertEqual(search.results.count(), 0)
        search.refresh_from_db()
        self.assertIsNone(search.recommended_offer)

    def test_failed_write_keeps_previous_results(self):
        offers = [self.offer(self.fast, "100")]
        search = self.search(city=self.tomsk)
        rank_and_save(search, offers)
        with patch("search.ranking.SearchResult.objects.bulk_create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                rank_and_save(search, offers)
        self.assertEqual(search.results.count(), 1)

    def test_delivery_failure_degrades_search_but_keeps_results(self):
        search = self.search(city=self.tomsk)
        with patch("search.ranking.calc_deliveries", side_effect=RuntimeError("boom")), \
                self.assertLogs("search.ranking", level="ERROR"):
            rank_and_save(search, [self.offer(self.fast, "5000")])
        search.refresh_from_db()
        self.assertTrue(search.degraded)
        result = self.saved(search)[0]
        self.assertEqual((result.delivery_price, result.delivery_source), (None, "unknown"))

    def test_query_count_does_not_grow_with_offers(self):
        search = self.search(city=self.tomsk)
        created = [self.offer(self.fast, "1000", "a"), self.offer(self.cheap, "1000", "b")]
        created += [self.offer(self.fast, str(2000 + i), f"x{i}") for i in range(10)]
        offers = list(Offer.objects.filter(pk__in=[o.pk for o in created]).select_related(
            "shop__origin_city", "product__category__parent"))
        with self.assertNumQueries(7):
            rank_and_save(search, offers)


class BuildProfileTests(RankingBase):

    def test_user_profile_is_used(self):
        user = self.user(delivery_priority="speed", budget_max=Decimal("50000"))
        profile = build_profile(self.search(user=user))
        self.assertEqual((profile["priority"], profile["budget_max"]), ("speed", Decimal("50000")))

    def test_prior_is_average_rating_of_active_shops_with_rating(self):
        Shop.objects.create(name="Плохой", rating=Decimal("3.5"))
        Shop.objects.create(name="Выключен", rating=Decimal("1.0"), is_active=False)
        Shop.objects.create(name="Без рейтинга")
        self.assertAlmostEqual(float(build_profile(self.search())["prior_rating"]), (4.5 + 4.5 + 3.5) / 3, places=2)


class BuildCandidateTests(RankingBase):
    def test_candidate_carries_offer_terms_and_delivery(self):
        from delivery.services import calc_delivery
        offer = self.offer(self.fast, "7000", warranty_months=36)
        delivery = calc_delivery(offer, self.tomsk)
        candidate = build_candidate(offer, delivery)
        self.assertEqual((candidate.price, candidate.delivery_price, candidate.delivery_days),
                         (Decimal("7000"), Decimal("500"), 2))
        self.assertEqual((candidate.warranty_months, candidate.return_days, candidate.rating_count), (36, 14, 1000))
        self.assertEqual(candidate.total_price, Decimal("7500"))
