import unittest
from scripts.build import parse, aggregate, create


def csv_bytes(records):
    head = 'JAHR;KW;WOHNORT;GESCHLECHT;ALTERSGRUPPE;STATION;COVID;INFLUENZA;RSV;PNEUMOKOKKEN;SONSTIGE;AUFNAHMEN;BEV_ZAHL'
    return ('\n'.join([head] + records) + '\n').encode()


class TestBuild(unittest.TestCase):
    def test_station_denominator_is_not_doubled(self):
        rows = parse(csv_bytes([
            '2026;43;Wien;W;00-04;N;1;0;0;0;0;2;1000',
            '2026;43;Wien;W;00-04;I;0;1;0;0;0;1;1000',
        ]), 'patient')
        result = aggregate(rows, ('week', 'region'), True)
        self.assertEqual(result[0]['population'], 1000)
        self.assertEqual(result[0]['aufnahmen'], 3)
        self.assertEqual(result[0]['aufnahmen_per_100k'], 300)

    def test_conflicting_denominators_rejected(self):
        rows = parse(csv_bytes([
            '2026;43;Wien;W;00-04;N;1;0;0;0;0;2;1000',
            '2026;43;Wien;W;00-04;I;0;1;0;0;0;1;1200',
        ]), 'patient')
        with self.assertRaises(ValueError):
            aggregate(rows, ('week', 'region'), True)

    def test_invalid_week(self):
        with self.assertRaises(ValueError):
            parse(csv_bytes(['2026;54;Wien;W;00-04;N;1;0;0;0;0;2;1000']), 'patient')

    def test_missing_column(self):
        with self.assertRaises(ValueError):
            parse(b'JAHR;KW\n2026;43\n', 'patient')


if __name__ == '__main__':
    unittest.main()
