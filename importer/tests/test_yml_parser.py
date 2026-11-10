import gc
import io
import tracemalloc
from xml.etree.ElementTree import ParseError

from django.test import SimpleTestCase

from importer.yml_parser import RawOffer, iter_offers

from .helpers import demo_feed, feed_xml, many_offers_feed, offer_xml


def parse(xml) -> list:
    return list(iter_offers(io.BytesIO(xml if isinstance(xml, bytes) else xml.encode("utf-8"))))


class IterOffersTests(SimpleTestCase):
    def test_vendor_model_offer(self):
        xml = feed_xml('<offer id="DR1" available="false" type="vendor.model">'
                       '<url>https://shop.example/p/1</url><price>62890</price><oldprice>67890</oldprice>'
                       '<currencyId>RUR</currencyId><categoryId>101</categoryId><typePrefix>Смартфон</typePrefix>'
                       '<vendor>Samsung</vendor><model>Galaxy S24 8/256GB</model><vendorCode>SM-S921B</vendorCode>'
                       '<warranty-days>P1Y</warranty-days><weight>0.450</weight>'
                       '<param name="Диагональ экрана" unit="дюйм">6.2</param></offer>')
        self.assertEqual(parse(xml), [RawOffer(
            id="DR1", available="false", type="vendor.model", url="https://shop.example/p/1", price="62890",
            oldprice="67890", currency_id="RUR", category_id="101", type_prefix="Смартфон", vendor="Samsung",
            model="Galaxy S24 8/256GB", vendor_code="SM-S921B", warranty_days="P1Y", weight="0.450",
            params=[("Диагональ экрана", "дюйм", "6.2")])])

    def test_simple_offer_with_name_tag(self):
        xml = feed_xml('<offer id="DN1"><name>Смартфон Samsung Galaxy S24</name><vendor>Samsung</vendor></offer>')
        [offer] = parse(xml)
        self.assertEqual((offer.id, offer.name, offer.type, offer.model),
                         ("DN1", "Смартфон Samsung Galaxy S24", "", ""))

    def test_missing_tags_and_attributes_are_empty_strings(self):
        [offer] = parse(feed_xml('<offer id="1"></offer>'))
        self.assertEqual(offer, RawOffer(id="1"))
        self.assertEqual((offer.available, offer.price, offer.params, offer.barcodes), ("", "", [], []))

    def test_whitespace_around_values_is_stripped(self):
        xml = feed_xml('<offer id=" 7 " available=" true ">\n  <price>\n    1000\n  </price>\n'
                       '  <vendor> Apple </vendor>\n</offer>')
        [offer] = parse(xml)
        self.assertEqual((offer.id, offer.available, offer.price, offer.vendor), ("7", "true", "1000", "Apple"))

    def test_shop_level_tags_do_not_leak_into_offers(self):
        xml = ('<yml_catalog><shop><name>DNS</name><url>https://dns.example</url><offers>'
               '<offer id="1"><price>5</price></offer></offers></shop></yml_catalog>')
        [offer] = parse(xml)
        self.assertEqual((offer.name, offer.url), ("", ""))

    def test_offers_come_in_feed_order(self):
        self.assertEqual([offer.id for offer in parse(many_offers_feed(5))], ["0", "1", "2", "3", "4"])

    def test_params_keep_order_and_missing_parts(self):
        xml = feed_xml('<offer id="1"><param name="Цвет">чёрный</param><param name="Вес" unit="кг">1</param>'
                       '<param unit="шт">2</param><param name="Пустой"/></offer>')
        [offer] = parse(xml)
        self.assertEqual(offer.params,
                         [("Цвет", "", "чёрный"), ("Вес", "кг", "1"), ("", "шт", "2"), ("Пустой", "", "")])

    def test_barcodes_from_several_tags_and_comma_separated(self):
        xml = feed_xml('<offer id="1"><barcode>4006381333931</barcode><barcode> 5901234123457 , 96385074 ,, </barcode>'
                       '<barcode/></offer>')
        [offer] = parse(xml)
        self.assertEqual(offer.barcodes, ["4006381333931", "5901234123457", "96385074"])

    def test_windows_1251_feed(self):
        xml = feed_xml(offer_xml("1", vendor="Хуавей"), encoding="windows-1251")
        self.assertEqual(parse(xml)[0].vendor, "Хуавей")

    def test_dtd_reference_of_demo_feeds_is_not_fetched(self):
        self.assertIn(b"shops.dtd", demo_feed("citilink.yml"))
        self.assertEqual(len(parse(demo_feed("citilink.yml"))), 16)

    def test_feed_without_offers(self):
        self.assertEqual(parse(feed_xml()), [])

    def test_broken_xml_raises_after_the_offers_before_it(self):
        broken = feed_xml(offer_xml("1"), offer_xml("2"))[:-60]
        offers = iter_offers(io.BytesIO(broken))
        self.assertEqual(next(offers).id, "1")
        with self.assertRaises(ParseError):
            list(offers)

    def test_not_xml_at_all(self):
        with self.assertRaises(ParseError):
            parse(b"<html>this is not a feed")
        with self.assertRaises(ParseError):
            parse(b"")

    def test_entity_expansion_bomb_is_rejected(self):
        entities = ['<!ENTITY a0 "lol">'] + [f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 9)]
        bomb = (f'<?xml version="1.0"?><!DOCTYPE yml_catalog [{"".join(entities)}]><yml_catalog><shop><offers>'
                '<offer id="1"><vendor>&a8;</vendor></offer></offers></shop></yml_catalog>')
        with self.assertRaises(ParseError):
            parse(bomb)

    def test_external_entities_are_not_read(self):
        xml = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><yml_catalog><shop>'
               '<offers><offer id="1"><vendor>&x;</vendor></offer></offers></shop></yml_catalog>')
        with self.assertRaises(ParseError):
            parse(xml)

    def test_memory_does_not_grow_with_feed_size(self):
        def peak(count):
            feed = io.BytesIO(many_offers_feed(count))
            gc.collect()
            tracemalloc.start()
            try:
                for _ in iter_offers(feed):
                    pass
                return tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        small, large = peak(2_000), peak(16_000)
        self.assertLess(large, 2 * small + 200_000)