import { useCallback, useEffect, useRef, useState } from 'react';
import { transcribeRecording } from '../../services/copilotService';

export type VoiceState = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'error';

const MAX_SECONDS = 300;

function pickMimeType(): string {
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  for (const t of options) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) return t;
  }
  return '';
}

/**
 * Microphone dictation: record -> upload -> local Whisper transcription -> onTranscript(text).
 * Exposes a 0..1 input level for a live meter and the elapsed seconds.
 */
export function useVoiceRecorder(onTranscript: (text: string) => void, opts: { stopOnSilence?: boolean; onNoSpeech?: () => void } = {}) {
  const [state, setState] = useState<VoiceState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const cancelledRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const transcriptCb = useRef(onTranscript);
  transcriptCb.current = onTranscript;
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const cleanup = useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    timerRef.current = null;
    rafRef.current = null;
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => undefined);
    audioCtxRef.current = null;
    setLevel(0);
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const supported =
    typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

  const start = useCallback(async () => {
    if (!supported) {
      setState('error');
      setError('This browser does not support microphone recording.');
      return;
    }
    setError(null);
    setState('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      chunksRef.current = [];
      cancelledRef.current = false;

      recorder.ondataavailable = e => { if (e.data.size) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        const type = recorder.mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type });
        cleanup();
        if (cancelledRef.current || blob.size === 0) { setState('idle'); return; }
        setState('transcribing');
        try {
          const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
          const res = await transcribeRecording(blob, `dictation.${ext}`);
          const text = (res.text || '').trim();
          if (!text) {
            if (optsRef.current.onNoSpeech) { setState('idle'); optsRef.current.onNoSpeech(); return; }
            setState('error');
            setError("I didn't catch any speech. Try again a little closer to the microphone.");
            return;
          }
          transcriptCb.current(text);
          setState('idle');
        } catch (e) {
          setState('error');
          setError(e instanceof Error ? e.message : String(e));
        }
      };

      // Live input level for the meter.
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const began = Date.now();
      let heard = false;
      let lastLoud = began;
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += ((v - 128) / 128) ** 2;
        const lvl = Math.min(1, Math.sqrt(sum / buf.length) * 4);
        setLevel(lvl);
        if (optsRef.current.stopOnSilence && recorder.state === 'recording') {
          const now = Date.now();
          if (lvl > 0.1) { lastLoud = now; if (now - began > 250) heard = true; }
          // hands-free: stop after ~1.4 s of quiet once speech was heard; give up after 15 s of silence
          if ((heard && now - lastLoud > 1400) || (!heard && now - began > 15000)) {
            if (!heard) cancelledRef.current = true;
            recorder.stop();
            if (!heard) optsRef.current.onNoSpeech?.();
          }
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();

      recorder.start(250);
      setSeconds(0);
      const startedAt = Date.now();
      timerRef.current = window.setInterval(() => {
        const s = Math.floor((Date.now() - startedAt) / 1000);
        setSeconds(s);
        if (s >= MAX_SECONDS && recorder.state === 'recording') recorder.stop();
      }, 250);
      setState('recording');
    } catch (e) {
      cleanup();
      setState('error');
      const name = e instanceof DOMException ? e.name : '';
      setError(
        name === 'NotAllowedError'
          ? 'Microphone access was blocked. Allow it in the browser address bar and try again.'
          : name === 'NotFoundError'
            ? 'No microphone was found.'
            : e instanceof Error ? e.message : String(e)
      );
    }
  }, [cleanup, supported]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    else { cleanup(); setState('idle'); }
  }, [cleanup]);

  const dismissError = useCallback(() => { setError(null); setState('idle'); }, []);

  return { state, error, seconds, level, supported, start, stop, cancel, dismissError };
}
