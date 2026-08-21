import unittest

from app.domain.adsorption_reference_energy import (
    AdsorptionReferenceEnergyCatalog,
)


class AdsorptionReferenceEnergyCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = AdsorptionReferenceEnergyCatalog()

    def test_known_intermediate_resolves_with_provenance(self):
        result = self.catalog.resolve("CO")

        self.assertEqual(
            result["resolved_reference_energy_ev"],
            -14.94164602,
        )
        self.assertEqual(result["energy_unit"], "eV")
        self.assertEqual(
            result["data_version"],
            "user-vasp-intermediates-2026-07-25-v1",
        )

    def test_alias_resolves_to_canonical_intermediate(self):
        result = self.catalog.resolve("HCO")

        self.assertEqual(result["canonical_adsorbate"], "CHO")
        self.assertEqual(
            result["resolved_reference_energy_ev"],
            -17.19120783,
        )

    def test_unlisted_intermediate_requires_user_input(self):
        self.assertIsNone(self.catalog.resolve("COOH"))


if __name__ == "__main__":
    unittest.main()
