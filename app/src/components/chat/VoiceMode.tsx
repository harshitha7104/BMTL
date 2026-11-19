import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Square, Volume2, X } from 'lucide-react';
import { useVoiceRecorder } from './useVoiceRecorder';

/**
 * Hands-free voice conversation (voice agent).
 *
 * Loop: listen -> stop on silence -> transcribe on the server (local Whisper) -> send as a chat message
 * -> speak the answer's short spoken summary with the device's own voices -> listen again.
 * Speech synthesis runs in the browser, so no audio of the answer leaves the PC. The full answer,
 * with tables and downloads, also appears in the chat behind this panel.
 */
type Phase = 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'paused';

interface Props {
  ask: (text: string) => Promise<string | null>;   // returns the text to speak
  onClose: () => void;
}

function pickVoice(): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  return voices.find(v => /en[-_](GB|IN|US)/i.test(v.lang) && /natural|neural|online/i.test(v.name))
    ?? voices.find(v => /^en/i.test(v.lang));
}

export default function VoiceMode({ ask, onClose }: Props) {
  const [phase, setPhase] = useState<Phase>('listening');
  const [heard, setHeard] = useState('');
  const [said, setSaid] = useState('');
  const open = useRef(true);
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;

  const listenAgain = useRef<() => void>(() => undefined);

  const speak = useCallback((text: string) => new Promise<void>(resolve => {
    if (!canSpeak || !text) { resolve(); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = pickVoice();
    if (v) u.voice = v;
    u.rate = 1.02;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    window.speechSynthesis.speak(u);
  }), [canSpeak]);

  const onTranscript = useCallback(async (text: string) => {
    if (!open.current) return;
    setHeard(text);
    setPhase('thinking');
    const answer = await ask(text);
    if (!open.current) return;
    setSaid(answer ?? "Sorry, I couldn't get an answer. Please try again.");
    setPhase('speaking');
    await speak(answer ?? "Sorry, I couldn't get an answer. Please try again.");
    if (open.current) listenAgain.current();
  }, [ask, speak]);

  const rec = useVoiceRecorder(onTranscript, {
    stopOnSilence: true,
    onNoSpeech: () => { if (open.current) setPhase('paused'); },
  });

  listenAgain.current = () => { setPhase('listening'); rec.start(); };

  useEffect(() => {
    open.current = true;
    listenAgain.current();
    return () => {
      open.current = false;
      if (canSpeak) window.speechSynthesis.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { if (rec.state === 'transcribing') setPhase('transcribing'); }, [rec.state]);

  const close = () => {
    open.current = false;
    rec.cancel();
    if (canSpeak) window.speechSynthesis.cancel();
    onClose();
  };

  const interrupt = () => {          // stop talking / stop listening now
    if (phase === 'speaking') { window.speechSynthesis.cancel(); return; }   // speak() resolves -> listens again
    if (phase === 'listening') rec.stop();
  };

  const label = rec.state === 'error' ? 'Microphone needed' : {
    listening: 'Listening… just talk',
    transcribing: 'Writing down what you said…',
    thinking: 'Your agents are working on it…',
    speaking: 'Speaking',
    paused: "I didn't hear anything",
  }[phase];
  const scale = phase === 'listening' ? 1 + rec.level * 0.6 : phase === 'speaking' ? 1.12 : 1;

  return (
    <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-ace-cream/95 px-6 backdrop-blur-sm" role="dialog" aria-label="Voice conversation">
      <button onClick={close} className="absolute right-4 top-4 rounded-full p-2 text-ace-muted hover:bg-ace-line/40 hover:text-ace-ink" title="End voice conversation">
        <X className="h-5 w-5" />
      </button>

      <div className="relative mb-8 flex h-44 w-44 items-center justify-center">
        <div
          className={`absolute inset-0 rounded-full bg-ace-terracotta/20 transition-transform duration-150 ${phase === 'thinking' || phase === 'transcribing' ? 'animate-pulse' : ''}`}
          style={{ transform: `scale(${scale})` }}
        />
        <div className="relative flex h-28 w-28 items-center justify-center rounded-full bg-ace-terracotta text-white shadow-lg">
          {phase === 'speaking' ? <Volume2 className="h-10 w-10" /> : <Mic className="h-10 w-10" />}
        </div>
      </div>

      <p className="text-lg font-medium text-ace-ink">{label}</p>
      {heard && <p className="mt-4 max-w-xl text-center text-sm text-ace-muted">You: “{heard}”</p>}
      {said && phase === 'speaking' && <p className="mt-3 max-w-xl text-center text-sm text-ace-ink">{said}</p>}
      {rec.error && <p className="mt-3 max-w-xl text-center text-sm text-red-600">{rec.error}</p>}
      {!canSpeak && <p className="mt-3 text-xs text-ace-muted">This browser cannot speak; answers are shown in the chat.</p>}

      <div className="mt-8 flex gap-3">
        {phase === 'paused' || rec.state === 'error' ? (
          <button onClick={() => { rec.dismissError(); listenAgain.current(); }}
                  className="flex items-center gap-2 rounded-full bg-ace-terracotta px-5 py-2.5 text-sm font-medium text-white hover:opacity-90">
            <Mic className="h-4 w-4" /> Tap to talk
          </button>
        ) : (
          <button onClick={interrupt} disabled={phase === 'thinking' || phase === 'transcribing'}
                  className="flex items-center gap-2 rounded-full border border-ace-line bg-white px-5 py-2.5 text-sm text-ace-ink hover:bg-ace-line/30 disabled:opacity-50">
            <Square className="h-4 w-4" /> {phase === 'speaking' ? 'Stop speaking' : "I'm done"}
          </button>
        )}
        <button onClick={close} className="rounded-full border border-ace-line bg-white px-5 py-2.5 text-sm text-ace-muted hover:text-ace-ink">
          End
        </button>
      </div>
      <p className="mt-6 max-w-md text-center text-[11px] text-ace-muted/80">
        Speech is transcribed on the ScrapTrust server and answers are spoken by your device. Full answers, tables and reports appear in the chat.
      </p>
    </div>
  );
}
