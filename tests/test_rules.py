import unittest

from backend.rules import scan


def block(text, **extra):
    return {"id": "p0", "text": text, "editable": True, "protected": [], **extra}


class WritingRulesTest(unittest.TestCase):
    def test_chinese_offsets_survive_emoji(self):
        text = "实验🧪。值得注意的是，误差降低了。"
        findings = scan([block(text)])
        self.assertEqual(findings[0]["quote"], "值得注意的是，")
        self.assertEqual(text[findings[0]["start"]:findings[0]["end"]], findings[0]["quote"])

    def test_english_leadin_is_exact_selection(self):
        text = "It is worth noting that the effect may be modest [3]."
        finding = scan([block(text)])[0]
        self.assertEqual(finding["category"], "空泛强调")
        self.assertNotIn("may", finding["quote"])
        self.assertNotIn("[3]", finding["quote"])

    def test_protected_and_noneditable_not_suggested(self):
        text = "值得注意的是，数据尚未复核。"
        self.assertEqual(scan([block(text, protected=[{"start": 0, "end": 7}])]), [])
        self.assertEqual(scan([block(text, editable=False)]), [])

    def test_scientific_qualification_and_citation_untouched(self):
        text = "结果可能受到样本量影响，应结合置信区间解释[12]。"
        self.assertEqual(scan([block(text)]), [])
        self.assertEqual(scan([block("The estimate may be biased; the 95% confidence interval is [0.1, 0.4].")]), [])

    def test_same_sentence_in_different_paragraphs_is_review_only(self):
        sentence = "The sampling interval remained unchanged throughout the experiment."
        rows = [block(sentence), block(sentence, id="p1")]
        finding = scan(rows)[0]
        self.assertEqual(finding["block_id"], "p1")
        self.assertEqual(finding["rule_id"], "repeated-sentence")
        self.assertNotIn("replacement", finding)

    def test_disable_rule(self):
        self.assertEqual(scan([block("值得注意的是，结果没有改变。")], {"disabled_rules": ["empty-emphasis"]}), [])

    def test_keeps_quoted_protected_text_out(self):
        text = "原句为：值得注意的是，结果稳定。"
        self.assertEqual(scan([block(text, protected=[{"start": 4, "end": len(text)}])]), [])


if __name__ == "__main__":
    unittest.main()
