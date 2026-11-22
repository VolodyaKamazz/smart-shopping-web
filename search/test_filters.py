from .test_ranking import RankingBase


class FilterBase(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)
        self.url = f"/results/{self.search.id}/api/"

    def ids(self, **params):
        return {i["offer_id"] for i in self.client.get(self.url, params).json()["items"]}

    def ids_multi(self, query):
        return {i["offer_id"] for i in self.client.get(f"{self.url}?{query}").json()["items"]}


class PriceFilterTests(FilterBase):
    def test_price_min(self):
        self.assertEqual(self.ids(price_min="28000"), {self.o_plain.id, self.o_fast.id})

    def test_price_max(self):
        self.assertEqual(self.ids(price_max="28000"), {self.o_cheap.id, self.o_plain.id})

    def test_price_range(self):
        self.assertEqual(self.ids(price_min="27500", price_max="29000"), {self.o_plain.id})

    def test_bounds_are_inclusive(self):
        self.assertEqual(self.ids(price_min="27000", price_max="27000"), {self.o_cheap.id})

    def test_decimal_with_dot_and_comma(self):
        self.assertEqual(self.ids(price_max="27000.5"), {self.o_cheap.id})
        self.assertEqual(self.ids(price_max="27000,5"), {self.o_cheap.id})

    def test_min_above_max_gives_nothing(self):
        self.assertEqual(self.ids(price_min="30000", price_max="1000"), set())

    def test_zero_max_gives_nothing(self):
        self.assertEqual(self.ids(price_max="0"), set())

    def test_garbage_is_ignored(self):
        for value in ("abc", "-5", "nan", "inf", "", "  "):
            with self.subTest(value=value):
                self.assertEqual(len(self.ids(price_min=value, price_max=value)), 3)

    def test_filter_uses_item_price_not_total(self):
        self.assertEqual(self.ids(price_max="27000"), {self.o_cheap.id})

    def test_count_matches_items(self):
        data = self.client.get(self.url, {"price_max": "28000"}).json()
        self.assertEqual(data["count"], len(data["items"]))
        self.assertEqual(data["count"], 2)


class ShopFilterTests(FilterBase):
    def test_by_id(self):
        self.assertEqual(self.ids(shop=str(self.cheap.id)), {self.o_cheap.id})

    def test_by_name_is_case_insensitive(self):
        self.assertEqual(self.ids(shop="дешёвый"), {self.o_cheap.id})
        self.assertEqual(self.ids(shop="БЫСТРЫЙ"), {self.o_fast.id})

    def test_several_shops_repeated_parameter(self):
        query = f"shop={self.cheap.id}&shop={self.fast.id}"
        self.assertEqual(self.ids_multi(query), {self.o_cheap.id, self.o_fast.id})

    def test_several_shops_comma_separated(self):
        self.assertEqual(self.ids(shop=f"{self.cheap.id},{self.plain.id}"), {self.o_cheap.id, self.o_plain.id})

    def test_id_and_name_together(self):
        self.assertEqual(self.ids_multi(f"shop={self.cheap.id}&shop=Быстрый"), {self.o_cheap.id, self.o_fast.id})

    def test_unknown_shop_gives_nothing(self):
        self.assertEqual(self.ids(shop="999999"), set())
        self.assertEqual(self.ids(shop="Несуществующий"), set())

    def test_empty_shop_is_ignored(self):
        self.assertEqual(len(self.ids(shop="")), 3)
        self.assertEqual(len(self.ids(shop=" , ")), 3)

    def test_shop_with_price(self):
        self.assertEqual(self.ids(shop=str(self.fast.id), price_max="28000"), set())
        self.assertEqual(self.ids(shop=str(self.cheap.id), price_max="28000"), {self.o_cheap.id})

    def test_shop_with_sort_and_days(self):
        data = self.client.get(self.url, {"shop": f"{self.fast.id},{self.cheap.id}", "sort": "price"}).json()
        self.assertEqual([i["offer_id"] for i in data["items"]], [self.o_cheap.id, self.o_fast.id])
        self.assertEqual(self.ids(shop=f"{self.fast.id},{self.cheap.id}", delivery_max_days="1"), {self.o_fast.id})

    def test_all_filters_together(self):
        self.assertEqual(
            self.ids(shop=f"{self.fast.id},{self.cheap.id},{self.plain.id}", price_min="27500", price_max="29000"),
            {self.o_plain.id})

    def test_html_page_uses_same_filters(self):
        response = self.client.get(f"/results/{self.search.id}/", {"shop": str(self.cheap.id)})
        self.assertEqual([i["offer_id"] for i in response.context["items"]], [self.o_cheap.id])


class ShopsListTests(FilterBase):
    def shops(self, **params):
        return self.client.get(self.url, params).json()["shops"]

    def test_lists_all_shops_with_counts_sorted_by_name(self):
        shops = self.shops()
        self.assertEqual([s["name"] for s in shops], sorted(s["name"] for s in shops))
        self.assertEqual({s["id"]: s["count"] for s in shops}, {self.fast.id: 1, self.cheap.id: 1, self.plain.id: 1})
        self.assertEqual(set(shops[0]), {"id", "name", "count"})

    def test_list_does_not_depend_on_filters(self):
        self.assertEqual(self.shops(shop=str(self.cheap.id), price_max="1"), self.shops())

    def test_shop_id_in_items(self):
        items = {i["offer_id"]: i for i in self.client.get(self.url).json()["items"]}
        self.assertEqual(items[self.o_cheap.id]["shop_id"], self.cheap.id)

    def test_counts_with_several_offers_in_one_shop(self):
        self.offers.append(self.offer(self.cheap, "29000"))
        search = self.run_for()
        data = self.client.get(f"/results/{search.id}/api/").json()
        counts = {s["id"]: s["count"] for s in data["shops"]}
        self.assertEqual(counts[self.cheap.id], 2)

    def test_empty_search_has_empty_shops(self):
        from .models import SearchRequest
        empty = SearchRequest.objects.create(user=self.user, raw_query="ничего", status="done")
        data = self.client.get(f"/results/{empty.id}/api/").json()
        self.assertEqual(data["shops"], [])
