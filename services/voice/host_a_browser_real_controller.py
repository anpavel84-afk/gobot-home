"""HOST-A REAL Browser Voice Lab turn: original Brain + original speech.

This is an adapter, NOT a second Brain. The existing gobot.brain Service,
ChatRequest/VoiceRequest, voiced_events and Speech synthesize every answer.
No transcript/audio saved in these diagnostics; the existing Brain's isolated
temporary state is cleaned when the browser session closes.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import time


async def finish_real_reply(lab):
    """One confirmed OpenAI STT turn -> existing Brain -> Marin PCM24 browser."""
    cloud = await lab.stream.verified_result()
    if cloud is not None:
        await lab.emit("cloud_verdict", status=cloud.verdict,
                       text=cloud.transcript, audio_seconds=cloud.audio_seconds)
    if cloud is None:
        await lab.emit("error", code="STT_FAILED_OR_TIMEOUT")
        lab.state = "ready"
        await lab.emit("state", value="ready")
        return
    is_initial = lab.current_turn_kind == "wake"
    accepted = (is_initial and cloud.verdict == "CONFIRMED") or (
        not is_initial and cloud.verdict == "FOLLOWUP"
        and lab.conversation_verified
        and lab.original_wake_event is not None)
    if not accepted or not cloud.question:
        lab.conversation_verified = False
        await lab.emit(
            "cloud_rejected", status=cloud.verdict,
            detail="No commands or reply: exact addressed name not confirmed")
        if lab.journal is not None:
            lab.journal.summarize_turn(
                lab.turn_count, outcome="NOT_CONFIRMED_"+cloud.verdict)
        lab.state = "ready"
        await lab.emit("state", value="ready")
        return
    # Either original cloud-verified Monika or a short, local-VAD-
    # triggered continuation, authenticated against that original wake.
    if is_initial:
        lab.conversation_verified = True
    booking = None
    started = time.monotonic()
    finish_status = "FAILED"
    audio_open = False
    audio_sent = 0
    got_final = False
    was_error = False
    first_text = False
    generation = lab.core.output_epoch
    try:
        # Capture the exact verified question BEFORE budget reservation,
        # so a rejected/failed Brain request remains fully explainable.
        await lab.emit("brain_question", question=cloud.question,
                       provider="original_gobot_brain")
        booking = await asyncio.to_thread(lab.budget.reserve_browser_dialog)
        await lab.emit(
            "brain_start", provider="original_gobot_brain",
            message="OpenAI-verifed Russian question -> existing GoBot Brain",
            tts_voice="marin", chat_model="gpt-4.1-mini",
            tts_model="gpt-realtime-2.1-mini")
        lab.state = "thinking"
        await lab.emit("state", value="thinking")
        if lab.brain is None:
            raise RuntimeError("existing_brain_not_initialized")
        async for item in lab.brain.response(
            question=cloud.question,
            device_id=lab.device_id,
            conversation_id=lab.conversation_id,
            turn_id="host-a-" + lab.epoch[:8] + "-" + str(lab.turn_count),
        ):
            kind = item.get("type")
            payload = item.get("data") or {}
            if lab.closing or lab.core.stop_pending or lab.core.output_epoch != generation:
                raise asyncio.CancelledError()
            if kind == "text_delta":
                text = payload.get("text", "")
                if not first_text:
                    first_text = True
                    await lab.emit("brain_first_text", provider="gobot_brain")
                if isinstance(text, str) and text:
                    await lab.emit("brain_delta", text=text[:1024])
            elif kind == "sentence_ready":
                text = payload.get("text")
                if isinstance(text, str) and text:
                    await lab.emit("brain_sentence", text=text[:512])
            elif kind == "tool_status":
                await lab.emit("brain_status", status=str(
                    payload.get("status") or "routing")[:60],
                    provider=str(payload.get("provider") or "")[:50],
                    route=str(payload.get("route") or "")[:80],
                    reason=str(payload.get("reason") or "")[:120],
                    model=str(payload.get("model") or "")[:80])
            elif kind == "audio_start":
                if audio_open:
                    raise RuntimeError("duplicate_voice_audio_start")
                audio_open = True
                lab.playback_active = True
                lab.core.playback(True, generation)
                lab.state = "speaking"
                await lab.emit("state", value="speaking")
                await lab.emit("tts_first_audio", provider="openai",
                               first_chunk_ms=payload.get("first_chunk_ms"))
                await lab.emit("audio_start", sample_rate=24000,
                               sample_format="pcm16le",
                               tts_voice="marin", provider="openai")
            elif kind == "audio_chunk":
                if not audio_open or payload.get("sample_rate") != 24000:
                    raise RuntimeError("invalid_real_tts_pcm_position")
                if payload.get("format") != "pcm_s16le":
                    raise RuntimeError("unexpected_tts_pcm_format")
                try:
                    data = base64.b64decode(payload.get("pcm") or "", validate=True)
                except (ValueError, binascii.Error):
                    raise RuntimeError("invalid_brain_tts_pcm_base64")
                if len(data) % 2 or not 0 < len(data) <= 32768:
                    raise RuntimeError("invalid_brain_tts_pcm_chunk")
                audio_sent += len(data)
                if audio_sent > 24000 * 2 * 16:
                    raise RuntimeError("voice_response_audio_bound_exceeded")
                async with lab.browser_send_lock:
                    await lab.ws.send_bytes(data)
            elif kind == "audio_stop":
                await lab.emit("audio_end", bytes_sent=audio_sent,
                               status=str(payload.get("reason") or "finished"))
            elif kind == "tts_error":
                was_error = True
                await lab.emit("error", code=str(payload.get("code") or "tts_failed"),
                               detail="Natural OpenAI speech failed; no fake answer")
            elif kind in ("error", "cancelled"):
                was_error = True
                await lab.emit("error", code=str(payload.get("code") or kind),
                               detail="Existing Brain rejected or cancelled answer")
            elif kind == "final":
                got_final = True
                await lab.emit(
                    "brain_final", text=str(payload.get("text") or "")[:2000],
                    provider=str(payload.get("provider") or "local")[:50],
                    total_ms=payload.get("total_ms"))
            elif kind == "widget_command":
                # Never silently execute a widget on phone. Existing Brain
                # enforces its own authorization, but this lab is not an
                # authorized physical home control frontend.
                await lab.emit("brain_widget_blocked",
                               code="browser_no_home_side_effects")
            # Other visual/trace records not transmitted to this voice lab.
        finish_status = "COMPLETE" if got_final and not was_error else "FAILED"
        lab.reply_completed = bool(got_final and audio_open and not was_error)
        if not audio_open:
            lab.state = "ready"
            await lab.emit("state", value="ready")
    except asyncio.CancelledError:
        finish_status = "CANCELLED"
        raise
    except Exception as exc:
        await lab.emit("error", code=type(exc).__name__,
                       detail="Real Brain/TTS turn stopped; no silent fallback")
        lab.state = "ready"
        await lab.emit("state", value="ready")
    finally:
        if booking:
            duration = max(0.0, time.monotonic() - started)
            kwargs={"elapsed_seconds":duration,"result":finish_status}
            if getattr(lab.budget,"supports_metered_settlement",False):
                # Exact Realtime output token counts from response.done when
                # provided, Chat token count explicitly tagged estimate.
                # Missing usage never silently becomes a zero-dollar turn.
                kwargs["usage"]=lab.brain.usage_snapshot()
            await asyncio.to_thread(lab.budget.finish, booking, **kwargs)
        try:
            budget = await asyncio.to_thread(lab.budget.status)
            await lab.emit(
                "budget_status",
                reserved_seconds=budget["reserved_seconds"],
                remaining_seconds=max(0, budget["max_seconds"] -
                                      budget["reserved_seconds"]),
                budget_estimate_usd=budget["reserved_estimated_usd"],
                remaining_estimated_usd=round(
                    budget["max_estimated_usd"] -
                    budget["reserved_estimated_usd"], 4),
                accounting_method=budget.get("billing_method","legacy"),
                historical_virtual_reserved_usd=budget.get(
                    "legacy_virtual_reserved_usd"),
                historical_reconciled_estimated_usd=budget.get(
                    "legacy_reconciled_estimated_usd"),
                provider_invoice_confirmed=budget.get(
                    "provider_invoice_confirmed",False))
        except Exception:
            pass
