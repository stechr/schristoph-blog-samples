"""
Gradio web app for the voice-sample studio (v3 — master-detail single page).

Thin UI layer: all scoring/export/storage/advice/preview logic lives in the
tested modules (quality, export, store, transcribe, mos, advice, preview).

v3 adds:
  * a bigger, more legible verdict card and clean (non-cramped) table headers,
  * MASTER-DETAIL: select a row in the takes table -> a detail panel renders on
    the same page (full scorecard, audio replay, editable name, keep/reject/
    delete/export) — replaces the v2 "Take id"/"New name" textboxes,
  * ACTIONABLE ADVICE side-by-side: BASIC (offline, rule-based) + RICH (Bedrock
    Claude; graceful-degrades to a note if unavailable),
  * VOICE PREVIEW: synthesize a preset or your own paragraph in the take's cloned
    voice (Qwen voice_clone) and play it back (graceful-degrades if the endpoint
    is unavailable).

Run (MOS enabled by default; +boto3 for rich advice & voice preview):

    uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
        --with librosa --with faster-whisper --with torch --with torchaudio \
        --with boto3 python -m voice_studio.app
    # or, with the project installed:  uv run voice-studio

Component licenses (all permissive): gradio (Apache-2.0), soundfile (BSD-3),
numpy (BSD-3), pyloudnorm (MIT), librosa (ISC), faster-whisper (MIT),
torch (BSD-3) / torchaudio (BSD-2) with SQUIM_OBJECTIVE weights (CC-BY-4.0),
boto3 (Apache-2.0).

Optional / graceful-degrade: drop --with librosa to disable pitch metrics, drop
--with faster-whisper to disable WPM/transcript/WER, drop --with torch torchaudio
to disable perceptual MOS, drop --with boto3 to disable rich advice + voice
preview. The app still runs and scores on whatever is present.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .quality import score_file, TARGET_LUFS
from .export import export_take
from .store import TakeStore, sanitize_name, sha1_of_file
from . import advice as advice_mod
from . import preview as preview_mod

# NOTE: gradio is imported at MODULE scope (not only inside build_app) so that the
# stringized `evt: gr.SelectData` annotation on the row-select handler resolves via
# the handler's module globals. With `from __future__ import annotations`, Gradio
# calls typing.get_type_hints() against __globals__ to detect the SelectData event
# arg; if `gr` lived only as a build_app local, detection failed and the handler was
# invoked with zero args ("Expected 1 arguments, received 0") — breaking master-detail.
import gradio as gr


DEFAULT_SCRIPT = (
    "Hello. My name is <name>, and this short recording captures the natural rhythm "
    "and tone of my voice. The quick brown fox jumps over the lazy dog, while five or "
    "six bright wizards quickly vex the grumpy judge. I tend to speak clearly, with "
    "steady pacing and gentle emphasis on the words that matter most. Numbers like one, "
    "two, three, and dates like the fourth of July help cover a wider range of sounds. "
    "Thank you for listening, and let's begin the walkthrough."
)

_VERDICT_STYLE = {
    "keep":   ("#1b7f3b", "#e7f6ec", "✅ KEEP"),
    "review": ("#9a6b00", "#fff7e0", "🟡 REVIEW"),
    "reject": ("#b3261e", "#fdecea", "⛔ REJECT"),
}

# CSS: kill Gradio's orange cell-selection box on the takes table (we drive
# selection via the row-select event, not a visible cell marker), and give the
# table a touch more breathing room so headers don't wrap/cramp.
_CSS = """
#takes-table table td.focus,
#takes-table table td.cell-selected,
#takes-table .cell-selected,
#takes-table td:focus,
#takes-table .table-wrap td.focus {
    background: transparent !important;
    box-shadow: none !important;
    outline: none !important;
    border-color: var(--border-color-primary) !important;
}
#takes-table table thead th {
    white-space: nowrap;
    font-weight: 600;
    padding: 8px 10px;
}
#takes-table table td { padding: 7px 10px; }
#detail-card { margin-top: 4px; }
"""


def _stars_str(n: int) -> str:
    n = max(0, min(5, int(n)))
    return "★" * n + "☆" * (5 - n)


def _verdict_card(sc: dict, take) -> str:
    """A big, legible verdict card (v3 — larger type, clear hierarchy)."""
    fg, bg, label = _VERDICT_STYLE.get(sc.get("verdict", "reject"), _VERDICT_STYLE["reject"])
    name = (getattr(take, "name", "") or "").strip()
    title = f"{name} · <code>{take.id}</code>" if name else f"<code>{take.id}</code>"
    chips = "".join(
        f"<span style='display:inline-block;background:#0000000f;border-radius:14px;"
        f"padding:4px 13px;margin:4px 6px 0 0;font-size:14px'>{l}</span>"
        for l in sc.get("labels", [])
    ) or "<span style='font-size:14px;color:#666'>(no labels)</span>"
    return (
        f"<div id='detail-card' style='border:3px solid {fg};background:{bg};border-radius:16px;"
        f"padding:20px 24px;margin:6px 0'>"
        f"<div style='display:flex;align-items:baseline;justify-content:space-between'>"
        f"<span style='font-size:32px;font-weight:800;color:{fg}'>{label}</span>"
        f"<span style='font-size:30px;letter-spacing:2px'>{_stars_str(sc.get('stars', 1))}</span>"
        f"</div>"
        f"<div style='font-size:52px;font-weight:800;color:#1a1a1a;line-height:1.05;margin-top:6px'>"
        f"{sc.get('overall_score', 0):.0f}"
        f"<span style='font-size:22px;font-weight:600;color:#666'> / 100 overall</span></div>"
        f"<div style='font-size:16px;color:#444;margin-top:6px'>"
        f"acoustic <b>{sc.get('objective_score', 0):.0f}</b> · "
        f"delivery <b>{sc.get('delivery_score', 0):.0f}</b>"
        + (f" · MOS <b>{sc['mos']:.2f}</b>" if sc.get('mos') is not None else "")
        + f" · {take.created_str} · {title}</div>"
        f"<div style='margin-top:12px'>{chips}</div>"
        f"</div>"
    )


def _fmt(v, suffix="", nd=1):
    return f"{v:.{nd}f}{suffix}" if v is not None else "n/a"


def _format_scorecard(sc: dict) -> str:
    lines = [
        "#### Acoustic",
        f"- Duration **{sc['duration']:.1f} s** · Sample rate **{sc['sample_rate']} Hz** · "
        f"Channels **{sc['channels']}** · Bit depth **{sc.get('bits_per_sample') or 'n/a'}**",
        f"- Integrated loudness **{_fmt(sc['integrated_lufs'],' LUFS')}** (norm target {TARGET_LUFS:.0f}) · "
        f"True peak **{sc['true_peak_dbtp']:.2f} dBTP** · Clipping **{sc['clipping_fraction']*100:.3f}%**",
        f"- Noise floor **{sc['noise_floor_dbfs']:.1f} dBFS** · SNR **{sc['snr_db']:.1f} dB** · "
        f"Bandwidth **{sc.get('bandwidth_hz', 0):.0f} Hz**",
        f"- Silence **{sc['silence_ratio']*100:.0f}%** · lead {sc['lead_trim_s']:.1f} s · "
        f"tail {sc['tail_trim_s']:.1f} s",
        "",
        "#### Delivery (how the clone will sound)",
        f"- Speaking rate **{_fmt(sc.get('wpm'),' WPM',0)}** "
        f"(articulation {_fmt(sc.get('articulation_wpm'),' WPM',0)}, "
        f"{sc.get('word_count') if sc.get('word_count') is not None else 'n/a'} words) "
        f"· _{sc.get('pace_backend')}_",
        f"- Pitch variation **{_fmt(sc.get('pitch_std_semitones'),' st')}** "
        f"(mean F0 {_fmt(sc.get('pitch_mean_hz'),' Hz',0)}, range "
        f"{_fmt(sc.get('pitch_range_semitones'),' st')}) · _{sc.get('pitch_backend')}_",
        f"- Loudness dynamics **{sc.get('loudness_dynamics_db', 0):.1f} dB**",
        f"- Pauses **{sc.get('pause_count', 0)}** "
        f"({sc.get('pauses_per_min', 0):.0f}/min, mean {sc.get('mean_pause_s', 0):.1f} s)",
        "",
        "#### Perceptual / transcript",
        f"- MOS **{_fmt(sc.get('mos'),'',2)}** ({sc['mos_backend']})",
        f"- Transcript ({sc['transcript_backend']}): "
        + (f"_{sc['transcript'][:240]}_" if sc['transcript'] else "_(none)_"),
    ]
    if sc.get("wer") is not None:
        lines.append(f"- WER vs target prompt: **{sc['wer']*100:.1f}%** (<name> token ignored)")
    if sc["issues"]:
        lines.append("\n**Issues:**")
        lines += [f"  - {i}" for i in sc["issues"]]
    return "\n".join(lines)


def _basic_advice_md(sc: dict) -> str:
    return "### 🟦 Basic advice (offline)\n" + advice_mod.basic_advice_markdown(sc)


def _rich_advice_md(sc: dict) -> str:
    text, status = advice_mod.rich_advice(sc)
    if text:
        return f"### 🟪 Rich advice (Bedrock)\n{text}\n\n<sub>_{status}_</sub>"
    return ("### 🟪 Rich advice (Bedrock)\n"
            f"> _Rich advice unavailable — {status}._\n>\n"
            "> Showing basic advice only. (Configure AWS credentials + `--with boto3` to enable.)")


def build_app(store: TakeStore):
    EMPTY_CARD = ("<div id='detail-card' style='border:2px dashed #bbb;border-radius:14px;"
                  "padding:22px;color:#777;text-align:center'>Select a recording in the "
                  "table above to see its full scorecard, replay it, rename it, get advice, "
                  "and generate a voice preview.</div>")

    def _render_detail(take):
        """Return the full detail-panel output tuple for a take (or cleared if None)."""
        if take is None:
            return ("", EMPTY_CARD, "", None, "", "", "",
                    "", None)
        sc = take.scorecard
        card = _verdict_card(sc, take)
        scard = _format_scorecard(sc)
        basic = _basic_advice_md(sc)
        rich = _rich_advice_md(sc)
        st = preview_mod.endpoint_status()
        pv_status = ("#### 🔊 Voice preview\n"
                     + ("✅ " if st["available"] else "⚠️ ") + st["message"])
        return (take.id, card, scard, take.master_wav, take.name or "",
                basic, rich, pv_status, None)

    def on_record(audio_path, target_text, take_name):
        if not audio_path:
            cleared = _render_detail(None)
            return ("<div style='padding:12px;color:#b3261e'>No audio captured.</div>",
                    "", store.as_rows(), None) + cleared
        ts = time.strftime("%Y%m%d-%H%M%S")
        master = store.root / f"take-{ts}.wav"
        shutil.copy2(audio_path, master)
        sha1 = sha1_of_file(master)
        sc = score_file(str(master), target_text=target_text or None)
        take = store.add(str(master), sc.to_dict(), name=(take_name or "").strip(), source_sha1=sha1)
        banner = _verdict_card(sc.to_dict(), take)
        md = _format_scorecard(sc.to_dict())
        # Auto-select the freshly recorded take into the detail panel.
        return (banner, md, store.as_rows(), str(master)) + _render_detail(take)

    def on_select(evt: gr.SelectData):
        row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        return _render_detail(store.take_at_row(row))

    def on_keep(take_id, keep):
        tid = (take_id or "").strip()
        if tid:
            store.set_kept(tid, keep)
        return (store.as_rows(),) + _render_detail(store.get(tid))

    def on_save_name(take_id, new_name):
        tid = (take_id or "").strip()
        if tid:
            store.set_name(tid, new_name or "")
        return (store.as_rows(),) + _render_detail(store.get(tid))

    def on_delete(take_id):
        tid = (take_id or "").strip()
        if tid:
            store.delete(tid)
        return (store.as_rows(),) + _render_detail(None)

    def on_export(take_id):
        t = store.get((take_id or "").strip())
        if not t:
            return "Select a take first."
        sc = t.scorecard
        ref = sc.get("transcript", "")
        base = sanitize_name(t.name, fallback="user_sample")
        out_dir = store.root / "exports" / t.id
        res = export_take(t.master_wav, out_dir, ref_text=ref, basename=base)
        return (
            f"Exported take `{t.id}`" + (f" ({t.name})" if t.name else "") + ":\n"
            f"- Master: `{res['master']}`\n"
            f"- Qwen 24 kHz mono: `{res['qwen_wav']}`\n"
            f"- ref_text.txt: `{res['ref_text']}`\n\n"
            f"Drop `{Path(res['qwen_wav']).name}` + `ref_text.txt` into "
            f"`qwen3-tts-video/recording/` to use as a voice_clone reference. "
            f"**Review ref_text.txt** — the clone needs the exact transcript."
        )

    def on_preview(take_id, preset_label, free_text):
        t = store.get((take_id or "").strip())
        if not t:
            return None, "Select a take first."
        text = (free_text or "").strip() or preview_mod.preset_text(preset_label)
        if not text:
            return None, "Pick a preset or type a paragraph to synthesize."
        st = preview_mod.endpoint_status()
        if not st["available"]:
            return None, f"⚠️ Preview unavailable — {st['message']}"
        res = preview_mod.generate_preview(t, text, store.root)
        if res.get("wav"):
            return res["wav"], (f"✅ Preview generated in {t.name or t.id}'s voice.\n\n"
                                f"Saved: `{res['wav']}`")
        return None, f"⚠️ Preview failed — {res.get('status')}"

    with gr.Blocks(title="Voice Sample Studio") as demo:
        gr.Markdown(
            "# 🎙️ Voice Sample Studio\n"
            "Record, score, and manage voice reference clips for the Qwen3-TTS "
            "`voice_clone` path. The clone **inherits the cadence, pace, pitch and "
            "timbre** of your reference — aim for clean, well-paced, expressive (not "
            "monotone) takes ~10–20 s long. Replace `<name>` in the script with your name."
        )
        target = gr.Textbox(
            label="Target script (read this aloud — used for WER; <name> is ignored)",
            value=DEFAULT_SCRIPT, lines=5,
        )
        with gr.Row():
            mic = gr.Audio(sources=["microphone", "upload"], type="filepath",
                           label="Record a take (or upload a wav)")
            with gr.Column():
                take_name = gr.Textbox(label="Take name (optional, used in export filenames)",
                                       placeholder="e.g. calm-take-1")
                rec_btn = gr.Button("🎯 Score this take", variant="primary")
                playback = gr.Audio(label="Last take playback", type="filepath")

        rec_banner = gr.HTML(label="Verdict")
        rec_report = gr.Markdown()

        gr.Markdown("## 📋 Recordings — select a row to open its detail view")
        table = gr.Dataframe(
            headers=store.COLUMNS, label="Takes (newest first — auto-updates on scoring)",
            interactive=False, wrap=True, elem_id="takes-table",
        )

        # ---- Master-detail: detail panel for the selected take --------------
        gr.Markdown("## 🔍 Detail")
        sel_state = gr.State("")
        detail_card = gr.HTML(EMPTY_CARD)
        with gr.Row():
            with gr.Column(scale=3):
                detail_scorecard = gr.Markdown()
            with gr.Column(scale=2):
                detail_audio = gr.Audio(label="▶ Replay this take", type="filepath")
                with gr.Row():
                    name_box = gr.Textbox(label="Name (editable — saved to the index & export slug)",
                                          placeholder="rename this take…", scale=3)
                    save_name_btn = gr.Button("💾 Save name", scale=1)
                with gr.Row():
                    keep_btn = gr.Button("✓ Keep")
                    reject_btn = gr.Button("✗ Reject")
                    del_btn = gr.Button("🗑 Delete", variant="stop")
                exp_btn = gr.Button("⬇ Export (master + Qwen ref)", variant="primary")
                exp_out = gr.Markdown()

        gr.Markdown("### 💡 Advice for your next recording")
        with gr.Row():
            basic_advice_md = gr.Markdown(scale=1)
            rich_advice_md = gr.Markdown(scale=1)

        gr.Markdown("### 🔊 Voice preview — hear a paragraph in this take's cloned voice")
        preview_status = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=2):
                preset_radio = gr.Radio(
                    choices=preview_mod.preset_choices(),
                    value=preview_mod.preset_choices()[0],
                    label="Preset paragraph",
                )
                free_text = gr.Textbox(
                    label="…or type your own paragraph (overrides the preset)",
                    placeholder="Type any text to hear it in this voice…", lines=3,
                )
                gen_btn = gr.Button("🎤 Generate preview", variant="primary")
            preview_audio = gr.Audio(label="▶ Cloned-voice preview", type="filepath", scale=2)

        # Detail output tuple order (shared by record/select/keep/rename/delete).
        detail_outputs = [sel_state, detail_card, detail_scorecard, detail_audio,
                          name_box, basic_advice_md, rich_advice_md,
                          preview_status, preview_audio]

        rec_btn.click(on_record, [mic, target, take_name],
                      [rec_banner, rec_report, table] + [playback] + detail_outputs)
        table.select(on_select, None, detail_outputs)
        keep_btn.click(lambda i: on_keep(i, True), sel_state, [table] + detail_outputs)
        reject_btn.click(lambda i: on_keep(i, False), sel_state, [table] + detail_outputs)
        save_name_btn.click(on_save_name, [sel_state, name_box], [table] + detail_outputs)
        del_btn.click(on_delete, sel_state, [table] + detail_outputs)
        exp_btn.click(on_export, sel_state, exp_out)
        gen_btn.click(on_preview, [sel_state, preset_radio, free_text],
                      [preview_audio, preview_status])
        demo.load(lambda: store.as_rows(), None, table)
    return demo


def main():
    store = TakeStore()
    demo = build_app(store)
    # allowed_paths lets Gradio serve the saved master WAV + previews from the
    # store dir (outside cwd/temp) for playback. css is passed here (Gradio 6
    # moved css from the Blocks constructor to launch()).
    demo.launch(server_name="127.0.0.1", inbrowser=True, show_error=True,
                css=_CSS, allowed_paths=[str(store.root)])


if __name__ == "__main__":
    main()
