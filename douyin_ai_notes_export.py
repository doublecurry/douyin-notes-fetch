#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import BrowserContext, Page, sync_playwright

DEFAULT_ENTRY_URL = "https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection"
DEFAULT_OUTPUT_DIR = "exports"
DEFAULT_PROFILE_DIR = ".browser-profile"
TRIGGER_PATTERNS = [
    re.compile(r"AI\s*笔记", re.IGNORECASE),
    re.compile(r"AI\s*字幕", re.IGNORECASE),
    re.compile(r"文字稿"),
    re.compile(r"文稿"),
    re.compile(r"字幕"),
]
PATH_PRIORITY_KEYWORDS = {
    "ai",
    "caption",
    "content",
    "note",
    "sentence",
    "speech",
    "subtitle",
    "summary",
    "text",
    "transcript",
    "utterance",
}
TEXT_FIELD_KEYS = ("text", "sentence", "content", "subtitle", "caption", "utterance", "summary")
UI_NOISE = (
    "点赞",
    "评论",
    "分享",
    "收藏",
    "关注",
    "首页",
    "直播",
    "搜索",
    "更多",
    "抖音",
    "作者",
    "合集",
    "收藏夹",
    "私信",
    "举报",
)


@dataclass
class TextCandidate:
    text: str
    score: int
    source: str


@dataclass
class ExportResult:
    index: int
    modal_id: str
    video_url: str
    title: str | None
    status: str
    output_file: str | None = None
    text_length: int = 0
    source: str | None = None
    reason: str | None = None


class ResponseBuffer:
    def __init__(self, max_entries: int = 80) -> None:
        self.max_entries = max_entries
        self.entries: list[tuple[str, str]] = []

    def bind(self, page: Page) -> None:
        def handler(response) -> None:
            url = response.url
            if "douyin.com" not in url:
                return
            try:
                content_type = response.headers.get("content-type", "")
            except Exception:
                content_type = ""
            if "json" not in content_type.lower() and not re.search(
                r"ai|aweme|caption|detail|item|note|subtitle|transcript", url, re.IGNORECASE
            ):
                return
            try:
                body = response.text()
            except Exception:
                return
            if not body or len(body) > 2_000_000:
                return
            self.entries.append((url, body))
            if len(self.entries) > self.max_entries:
                self.entries = self.entries[-self.max_entries :]

        page.on("response", handler)


def normalize_text(value: str, keep_newlines: bool = True) -> str:
    value = value.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    if keep_newlines:
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
    else:
        value = re.sub(r"\s+", " ", value)
    return value.strip()


def slugify(value: str, default: str = "collection") -> str:
    value = normalize_text(value, keep_newlines=False)
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return value[:80] or default


def strip_modal_id(url: str) -> str:
    parts = list(urlparse(url))
    query = parse_qs(parts[4], keep_blank_values=True)
    query.pop("modal_id", None)
    parts[4] = "&".join(f"{key}={values[-1]}" for key, values in query.items())
    return urlunparse(parts)


def get_modal_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("modal_id", ["unknown"])[0]


def score_text(text: str, source: str) -> int:
    score = min(len(text), 5000)
    lowered = source.lower()
    if any(keyword in lowered for keyword in PATH_PRIORITY_KEYWORDS):
        score += 2000
    if text.count("\n") >= 2:
        score += 300
    if sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff") >= 20:
        score += 300
    if len(re.findall(r"[。！？；,.!?;]", text)) >= 4:
        score += 120
    if any(noise in text for noise in UI_NOISE):
        score -= 250
    return score


def is_meaningful_text(value: str) -> bool:
    text = normalize_text(value)
    if len(text) < 20 or len(text) > 20_000:
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return False
    if text.count("{") > 8 and text.count("}") > 8:
        return False
    return True


def maybe_join_segments(node: list[Any], path: tuple[str, ...]) -> list[TextCandidate]:
    results: list[TextCandidate] = []
    for key in TEXT_FIELD_KEYS:
        parts: list[str] = []
        for item in node:
            if not isinstance(item, dict):
                parts = []
                break
            value = item.get(key)
            if not isinstance(value, str):
                parts = []
                break
            normalized = normalize_text(value)
            if not normalized:
                continue
            parts.append(normalized)
        if len(parts) >= 2:
            text = "\n".join(parts)
            source = f"{'.'.join(path)}[{key}]"
            results.append(TextCandidate(text=text, score=score_text(text, source), source=source))
    return results


def extract_json_candidates(node: Any, path: tuple[str, ...] = ()) -> list[TextCandidate]:
    candidates: list[TextCandidate] = []
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = path + (str(key),)
            if isinstance(value, str) and is_meaningful_text(value):
                text = normalize_text(value)
                source = ".".join(next_path)
                candidates.append(TextCandidate(text=text, score=score_text(text, source), source=source))
            elif isinstance(value, (dict, list)):
                candidates.extend(extract_json_candidates(value, next_path))
    elif isinstance(node, list):
        candidates.extend(maybe_join_segments(node, path))
        for idx, item in enumerate(node[:300]):
            if isinstance(item, (dict, list)):
                candidates.extend(extract_json_candidates(item, path + (str(idx),)))
            elif isinstance(item, str) and is_meaningful_text(item):
                text = normalize_text(item)
                source = ".".join(path + (str(idx),))
                candidates.append(TextCandidate(text=text, score=score_text(text, source), source=source))
    return dedupe_candidates(candidates)


def dedupe_candidates(candidates: list[TextCandidate]) -> list[TextCandidate]:
    best_by_text: dict[str, TextCandidate] = {}
    for candidate in candidates:
        key = normalize_text(candidate.text)
        current = best_by_text.get(key)
        if current is None or candidate.score > current.score:
            best_by_text[key] = candidate
    return sorted(best_by_text.values(), key=lambda item: item.score, reverse=True)


def extract_best_candidate_from_responses(buffer: ResponseBuffer) -> TextCandidate | None:
    all_candidates: list[TextCandidate] = []
    for url, body in reversed(buffer.entries):
        try:
            data = json.loads(body)
        except Exception:
            continue
        for candidate in extract_json_candidates(data):
            candidate.source = f"response:{url}#{candidate.source}"
            candidate.score += 200
            if re.search(r"ai|caption|note|subtitle|transcript", url, re.IGNORECASE):
                candidate.score += 300
            all_candidates.append(candidate)
    return dedupe_candidates(all_candidates)[0] if all_candidates else None


def snapshot_visible_text_candidates(page: Page) -> list[TextCandidate]:
    raw = page.evaluate(
        """
        () => {
          const tags = 'div,section,article,aside,p,span,li,h1,h2,h3'.split(',');
          const items = [];
          for (const tag of tags) {
            for (const el of document.querySelectorAll(tag)) {
              const style = window.getComputedStyle(el);
              if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
              const rect = el.getBoundingClientRect();
              if (rect.width < 16 || rect.height < 12) continue;
              const text = (el.innerText || '')
                .replace(/\\u00a0/g, ' ')
                .replace(/[ \\t]+\\n/g, '\\n')
                .replace(/\\n{3,}/g, '\\n\\n')
                .trim();
              if (!text || text.length < 20 || text.length > 12000) continue;
              items.push({
                text,
                tag: el.tagName,
                className: String(el.className || ''),
                rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
              });
            }
          }
          return items;
        }
        """
    )
    candidates: list[TextCandidate] = []
    for item in raw:
        text = normalize_text(item["text"])
        source = f"dom:{item['tag']}:{item['className']}"
        candidates.append(TextCandidate(text=text, score=score_text(text, source), source=source))
    return dedupe_candidates(candidates)


def pick_best_dom_candidate(before: list[TextCandidate], after: list[TextCandidate]) -> TextCandidate | None:
    before_set = {normalize_text(item.text) for item in before}
    novel = [item for item in after if normalize_text(item.text) not in before_set]
    if novel:
        return dedupe_candidates(novel)[0]
    return after[0] if after else None


def click_ai_note_trigger(page: Page) -> str | None:
    for pattern in TRIGGER_PATTERNS:
        locator = page.get_by_text(pattern)
        try:
            count = min(locator.count(), 8)
        except Exception:
            count = 0
        for idx in range(count):
            candidate = locator.nth(idx)
            try:
                if candidate.is_visible():
                    candidate.click(timeout=2000)
                    page.wait_for_timeout(1200)
                    return pattern.pattern
            except Exception:
                continue
    return None


def wait_for_login_if_needed(page: Page) -> None:
    page.wait_for_timeout(3000)
    title = page.title()
    if "验证码" in title or "登录" in title or "login" in page.url.lower():
        print("检测到登录/验证码页面。请在已打开的浏览器中完成登录或验证，然后回到终端按回车继续。")
        input()
        page.wait_for_timeout(2000)


def ensure_page_ready(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    wait_for_login_if_needed(page)
    page.wait_for_timeout(2500)


def navigate_to_collection(page: Page, args: argparse.Namespace) -> str:
    if args.collection_url:
        target = strip_modal_id(args.collection_url)
        ensure_page_ready(page, target)
        return target

    ensure_page_ready(page, args.entry_url)
    if args.collection_name:
        clicked = False
        try:
            locator = page.get_by_text(args.collection_name, exact=True)
            count = min(locator.count(), 6)
            for idx in range(count):
                item = locator.nth(idx)
                if item.is_visible():
                    item.click(timeout=2500)
                    clicked = True
                    break
        except Exception:
            clicked = False
        if clicked:
            page.wait_for_timeout(2500)
            return strip_modal_id(page.url)

    print("请在浏览器中手动打开目标收藏夹页面（保持在视频列表视图，不要停在单个视频弹层），完成后回到终端按回车继续。")
    input()
    page.wait_for_timeout(2000)
    return strip_modal_id(page.url)


def collect_video_urls(page: Page, max_rounds: int = 40) -> list[str]:
    seen: dict[str, None] = {}
    stable_rounds = 0
    last_count = -1
    for _ in range(max_rounds):
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(el => el.href)")
        for href in hrefs:
            full_url = urljoin(page.url, href)
            if "modal_id=" in full_url:
                seen[full_url] = None
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1600)
        count = len(seen)
        if count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = count
        if stable_rounds >= 4:
            break
    return list(seen.keys())


def best_title(page: Page, modal_id: str) -> str | None:
    for selector in ('meta[property="og:title"]', "title"):
        try:
            if selector.startswith("meta"):
                value = page.locator(selector).first.get_attribute("content")
            else:
                value = page.title()
            if value:
                value = normalize_text(value, keep_newlines=False)
                if value and value not in {"抖音", "验证码中间页"}:
                    return value
        except Exception:
            continue
    return modal_id


def choose_best_extraction(dom_candidate: TextCandidate | None, response_candidate: TextCandidate | None) -> TextCandidate | None:
    if dom_candidate and response_candidate:
        return dom_candidate if dom_candidate.score >= response_candidate.score else response_candidate
    return dom_candidate or response_candidate


def export_text(output_dir: Path, filename_base: str, text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{filename_base}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def process_video(
    context: BrowserContext,
    video_url: str,
    output_dir: Path,
    index: int,
    timeout_ms: int,
) -> ExportResult:
    modal_id = get_modal_id(video_url)
    page = context.new_page()
    responses = ResponseBuffer()
    responses.bind(page)
    try:
        ensure_page_ready(page, video_url)
        title = best_title(page, modal_id)
        before = snapshot_visible_text_candidates(page)
        trigger = click_ai_note_trigger(page)
        if not trigger:
            return ExportResult(
                index=index,
                modal_id=modal_id,
                video_url=video_url,
                title=title,
                status="skipped",
                reason="未找到 AI 笔记/字幕入口",
            )

        page.wait_for_timeout(timeout_ms)
        after = snapshot_visible_text_candidates(page)
        dom_candidate = pick_best_dom_candidate(before, after)
        response_candidate = extract_best_candidate_from_responses(responses)
        candidate = choose_best_extraction(dom_candidate, response_candidate)
        if not candidate or len(candidate.text) < 20:
            return ExportResult(
                index=index,
                modal_id=modal_id,
                video_url=video_url,
                title=title,
                status="skipped",
                reason="点击 AI 笔记后未提取到有效文本",
            )

        filename_base = f"{index:04d}_{slugify(modal_id)}"
        path = export_text(output_dir, filename_base, candidate.text)
        return ExportResult(
            index=index,
            modal_id=modal_id,
            video_url=video_url,
            title=title,
            status="exported",
            output_file=str(path),
            text_length=len(candidate.text),
            source=candidate.source,
        )
    finally:
        page.close()


def detect_collection_name(page: Page, fallback: str = "collection") -> str:
    if page.title() and page.title() not in {"抖音", "验证码中间页"}:
        title = normalize_text(page.title(), keep_newlines=False)
        title = title.replace(" - 抖音", "").strip()
        if title:
            return title
    for selector in ("h1", "h2", "h3"):
        try:
            text = normalize_text(page.locator(selector).first.inner_text(), keep_newlines=False)
        except Exception:
            text = ""
        if text and len(text) <= 60 and text not in UI_NOISE:
            return text
    return fallback


def launch_context(playwright, profile_dir: Path, headless: bool, channel: str | None) -> BrowserContext:
    options = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "locale": "zh-CN",
        "viewport": {"width": 1600, "height": 1200},
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    last_error: Exception | None = None
    channels = [channel] if channel else []
    for candidate_channel in channels + [None]:
        try:
            context = playwright.chromium.launch_persistent_context(
                channel=candidate_channel, **options
            )
            context.set_default_timeout(8000)
            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """
            )
            return context
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量导出抖音收藏夹视频中的 AI 笔记/AI 字幕文本。")
    parser.add_argument("--entry-url", default=DEFAULT_ENTRY_URL, help="收藏夹入口页 URL。")
    parser.add_argument("--collection-url", help="目标收藏夹 URL；如果传入单个视频 URL，会自动去掉 modal_id。")
    parser.add_argument("--collection-name", help="目标收藏夹名称；找不到时会回退为手动选择。")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="导出目录。")
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIR, help="Playwright 持久化浏览器目录。")
    parser.add_argument("--channel", default="chrome", help="浏览器 channel，默认 chrome；失败会自动回退。")
    parser.add_argument("--timeout-ms", type=int, default=2200, help="点击 AI 笔记后等待内容稳定的毫秒数。")
    parser.add_argument("--limit", type=int, help="只处理前 N 个视频，便于试跑。")
    parser.add_argument("--headless", action="store_true", help="无头模式；通常不建议，因为登录/验证码更难处理。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profile_dir = Path(args.profile_dir).resolve()
    output_root = Path(args.output_dir).resolve()

    with sync_playwright() as playwright:
        context = launch_context(playwright=playwright, profile_dir=profile_dir, headless=args.headless, channel=args.channel)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            collection_url = navigate_to_collection(page, args)
            if page.url != collection_url:
                ensure_page_ready(page, collection_url)

            collection_name = args.collection_name or detect_collection_name(page)
            safe_collection_name = slugify(collection_name)
            output_dir = output_root / safe_collection_name
            video_urls = collect_video_urls(page)
            if not video_urls:
                print("未抓到任何视频 URL。请确认当前页面是目标收藏夹的视频列表视图。", file=sys.stderr)
                return 2

            if args.limit:
                video_urls = video_urls[: args.limit]

            print(f"目标收藏夹：{collection_name}")
            print(f"共发现 {len(video_urls)} 个视频，开始提取 AI 笔记/字幕……")

            results: list[ExportResult] = []
            for idx, video_url in enumerate(video_urls, start=1):
                try:
                    result = process_video(
                        context=context,
                        video_url=video_url,
                        output_dir=output_dir,
                        index=idx,
                        timeout_ms=args.timeout_ms,
                    )
                except PlaywrightTimeoutError as exc:
                    result = ExportResult(
                        index=idx,
                        modal_id=get_modal_id(video_url),
                        video_url=video_url,
                        title=None,
                        status="skipped",
                        reason=f"页面超时：{exc}",
                    )
                except Exception as exc:
                    result = ExportResult(
                        index=idx,
                        modal_id=get_modal_id(video_url),
                        video_url=video_url,
                        title=None,
                        status="skipped",
                        reason=f"异常：{exc}",
                    )
                results.append(result)
                status_line = (
                    f"[{idx}/{len(video_urls)}] {result.modal_id} -> {result.status}"
                    + (f" ({result.reason})" if result.reason else "")
                )
                print(status_line)

            output_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "collection_name": collection_name,
                "collection_url": collection_url,
                "output_dir": str(output_dir),
                "total_videos": len(video_urls),
                "exported": sum(1 for item in results if item.status == "exported"),
                "skipped": sum(1 for item in results if item.status != "exported"),
                "results": [asdict(item) for item in results],
            }
            manifest_path = output_dir / "index.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"\n导出完成：{manifest['exported']} 个成功，{manifest['skipped']} 个跳过。")
            print(f"清单文件：{manifest_path}")
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
