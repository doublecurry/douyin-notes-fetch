import json
import unittest

from douyin_ai_notes_export import (
    ResponseBuffer,
    extract_best_candidate_from_responses,
    extract_json_candidates,
    get_modal_id,
    slugify,
    strip_modal_id,
)


class ExporterHelpersTest(unittest.TestCase):
    def test_strip_modal_id(self) -> None:
        url = "https://www.douyin.com/user/self?from_tab_name=main&modal_id=123456&showTab=favorite_collection"
        self.assertEqual(
            strip_modal_id(url),
            "https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection",
        )

    def test_get_modal_id(self) -> None:
        self.assertEqual(get_modal_id("https://example.com?a=1&modal_id=9988"), "9988")

    def test_slugify(self) -> None:
        self.assertEqual(slugify('我的 收藏夹: "学习/课程"'), "我的_收藏夹_学习_课程")

    def test_extract_json_candidates_prefers_joined_segments(self) -> None:
        payload = {
            "data": {
                "ai_note": {
                    "segments": [
                        {"text": "第一句内容。"},
                        {"text": "第二句内容。"},
                        {"text": "第三句内容。"},
                    ]
                }
            }
        }
        candidates = extract_json_candidates(payload)
        self.assertTrue(candidates)
        self.assertIn("第一句内容。", candidates[0].text)
        self.assertIn("第三句内容。", candidates[0].text)

    def test_extract_best_candidate_from_responses(self) -> None:
        payload = {
            "data": {
                "note_detail": {
                    "summary": "这是一段比较长的 AI 笔记文本，用于测试导出逻辑是否会优先选择高相关内容。"
                }
            }
        }
        buffer = ResponseBuffer()
        buffer.entries.append(("https://www.douyin.com/aweme/v1/web/note/detail/", json.dumps(payload, ensure_ascii=False)))
        candidate = extract_best_candidate_from_responses(buffer)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertIn("AI 笔记文本", candidate.text)
        self.assertIn("note/detail", candidate.source)


if __name__ == "__main__":
    unittest.main()
