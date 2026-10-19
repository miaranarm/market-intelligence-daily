import unittest

from src.enrichment import clean_summary


class CleanSummaryQualityTests(unittest.TestCase):
    def test_decodes_entities_and_removes_html_markup(self):
        self.assertEqual(
            clean_summary("<p>Markets &amp; banks remain under pressure.</p>"),
            "Markets & banks remain under pressure.",
        )

    def test_removes_script_and_style_contents(self):
        self.assertEqual(
            clean_summary("Useful market update. <script>fake hidden text</script> Next sentence."),
            "Useful market update. Next sentence.",
        )

    def test_removes_publisher_boilerplate_after_html_cleanup(self):
        result = clean_summary(
            "<p>Investors await the central bank decision.</p> "
            "<p>Subscribe to our newsletter for more updates.</p>"
        )
        self.assertEqual(result, "Investors await the central bank decision.")

    def test_empty_input_is_safe(self):
        self.assertEqual(clean_summary(""), "")


if __name__ == "__main__":
    unittest.main()
