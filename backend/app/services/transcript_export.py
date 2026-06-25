"""会议转写结果 HTML 导出 — 移植自 ASR_skill 的 make_copy_page.py。

生成带一键复制功能的双栏对比页面（逐字稿 + AI 优化稿）。
"""

from __future__ import annotations

import html
from typing import Literal


def _speaker_to_letter(label: str) -> str:
    """将 SPEAKER_00 → A, SPEAKER_01 → B, ..."""
    if label.upper().startswith("SPEAKER_"):
        try:
            idx = int(label.rsplit("_", 1)[-1])
            return chr(ord("A") + idx)
        except (ValueError, IndexError):
            return label
    return label


def _format_segments_as_text(segments: list[dict], use_letters: bool = True) -> str:
    """将 segment 列表格式化为可读文本，带说话人标签。"""
    lines = []
    for seg in segments:
        speaker = seg.get("speaker_label", "?")
        text = seg.get("text", "")
        if use_letters:
            speaker = _speaker_to_letter(speaker)
        lines.append(f"{speaker}：{text}")
    return "\n\n".join(lines)


def build_transcript_page(
    title: str,
    meeting_id: int,
    verbatim_text: str,
    optimized_text: str | None = None,
    version: Literal["both", "verbatim", "optimized"] = "both",
) -> str:
    """构建 HTML 转写结果页面。

    Args:
        title: 会议标题
        meeting_id: 会议 ID
        verbatim_text: 原始逐字稿
        optimized_text: AI 优化稿（可选）
        version: 显示模式 — "both" 双栏, "verbatim" 仅逐字稿, "optimized" 仅优化稿
    """
    show_verbatim = version in ("both", "verbatim")
    show_optimized = version == "both" and optimized_text
    single_column = not (show_verbatim and show_optimized)

    display_text = (
        verbatim_text if version == "verbatim"
        else (optimized_text or verbatim_text) if version == "optimized"
        else verbatim_text
    )

    grid_style = "grid-template-columns: 1fr;" if single_column else ""

    sections = ""
    if show_verbatim and show_optimized:
        sections = f"""
    <div class="grid" style="{grid_style}">
      <section>
        <div class="bar"><h2>逐字稿</h2><button onclick="copyText('verbatim', this)">复制逐字稿</button></div>
        <textarea id="verbatim" spellcheck="false" readonly>{html.escape(verbatim_text)}</textarea>
      </section>
      <section>
        <div class="bar"><h2>AI 优化稿</h2><button onclick="copyText('optimized', this)">复制优化稿</button></div>
        <textarea id="optimized" spellcheck="false" readonly>{html.escape(optimized_text or "")}</textarea>
      </section>
    </div>"""
    else:
        label = "逐字稿" if version == "verbatim" else "AI 优化稿"
        txt_id = "verbatim" if version == "verbatim" else "optimized"
        btn_label = "复制逐字稿" if version == "verbatim" else "复制优化稿"
        sections = f"""
    <section>
      <div class="bar"><h2>{html.escape(label)}</h2><button onclick="copyText('{txt_id}', this)">{btn_label}</button></div>
      <textarea id="{txt_id}" spellcheck="false" readonly>{html.escape(display_text)}</textarea>
    </section>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)} — 会议转写</title>
<style>
  :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  body {{ margin: 0; background: #f6f7f7; color: #232323; }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 40px; }}
  header {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; margin-bottom: 20px; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; }}
  p {{ margin: 0; color: #666; line-height: 1.5; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  section {{ background: #fff; border: 1px solid #d8dddc; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
  .bar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-bottom: 1px solid #e0e5e4; background: #fbfcfc; }}
  h2 {{ font-size: 16px; margin: 0; }}
  button {{ border: 1px solid #245f6f; background: #245f6f; color: #fff; border-radius: 6px; padding: 8px 12px; font-size: 14px; cursor: pointer; }}
  button:active {{ transform: translateY(1px); }}
  textarea {{ box-sizing: border-box; width: 100%; height: 72vh; border: 0; padding: 14px; resize: vertical; font-size: 14px; line-height: 1.75; color: #222; background: #fff; }}
  .note {{ font-size: 13px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} textarea {{ height: 60vh; }} header {{ display: block; }} }}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>{html.escape(title)}</h1>
      <p>会议转写结果，支持一键复制。</p>
    </div>
    <p class="note">会议 ID: {meeting_id}</p>
  </header>
  {sections}
</main>
<script>
async function copyText(id, btn) {{
  const el = document.getElementById(id);
  el.focus(); el.select();
  await navigator.clipboard.writeText(el.value);
  const old = btn.textContent;
  btn.textContent = '已复制';
  setTimeout(() => btn.textContent = old, 1200);
}}
</script>
</body>
</html>"""
