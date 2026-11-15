import { useCallback, useEffect, useRef, useState } from 'react';

export type OrbitalAudioCue = 'select' | 'focus' | 'scan' | 'complete';

type AudioWindow = Window & { webkitAudioContext?: typeof AudioContext };
type Voice = { oscillator: OscillatorNode; gain: GainNode };

function audioConstructor(): typeof AudioContext | undefined {
  if (typeof window === 'undefined') return undefined;
  return window.AudioContext ?? (window as AudioWindow).webkitAudioContext;
}

/** Short synthesized UI sounds. No audio context is opened until sound is enabled. */
export default function useOrbitalAudio() {
  const [enabled, setEnabled] = useState(false);
  const [available, setAvailable] = useState(() => Boolean(audioConstructor()));
  const wanted = useRef(false);
  const mounted = useRef(true);
  const generation = useRef(0);
  const context = useRef<AudioContext | null>(null);
  const master = useRef<GainNode | null>(null);
  const voices = useRef(new Set<Voice>());

  const stopVoices = useCallback(() => {
    for (const voice of voices.current) {
      voice.oscillator.onended = null;
      try { voice.oscillator.stop(); } catch { /* Already ended. */ }
      voice.oscillator.disconnect();
      voice.gain.disconnect();
    }
    voices.current.clear();
  }, []);

  const renderCue = useCallback((cue: OrbitalAudioCue, ctx: AudioContext) => {
    const output = master.current;
    if (!output || !wanted.current || document.hidden || ctx.state !== 'running') return;
    // A bounded voice count also limits rapid repeated clicks.
    if (voices.current.size > 18) stopVoices();
    const now = ctx.currentTime + 0.006;
    const tone = (
      frequency: number,
      duration: number,
      level: number,
      delay = 0,
      endFrequency = frequency,
      type: OscillatorType = 'sine',
      attack = 0.015,
    ) => {
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      const start = now + delay;
      oscillator.type = type;
      oscillator.frequency.setValueAtTime(frequency, start);
      oscillator.frequency.exponentialRampToValueAtTime(endFrequency, start + duration);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(level, start + Math.min(attack, duration / 3));
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(gain);
      gain.connect(output);
      const voice = { oscillator, gain };
      voices.current.add(voice);
      oscillator.onended = () => {
        oscillator.disconnect();
        gain.disconnect();
        voices.current.delete(voice);
      };
      oscillator.start(start);
      oscillator.stop(start + duration + 0.02);
    };

    switch (cue) {
      case 'select':
        tone(760, 0.085, 0.3, 0, 1040);
        tone(1500, 0.06, 0.09, 0.035);
        break;
      case 'focus':
        tone(84, 1.7, 0.34, 0, 220, 'sine', 0.45);
        tone(168, 1.5, 0.14, 0.09, 440, 'triangle', 0.4);
        tone(420, 0.9, 0.1, 0.6, 760, 'sine', 0.25);
        break;
      case 'scan':
        tone(130, 0.7, 0.2, 0, 180, 'sine', 0.08);
        [0, 0.32, 0.64, 0.96].forEach((delay, index) => {
          tone(680 + index * 95, 0.17, 0.21, delay, 850 + index * 95);
          tone(1360 + index * 190, 0.12, 0.055, delay + 0.025);
        });
        break;
      case 'complete':
        tone(523.25, 0.6, 0.23);
        tone(659.25, 0.65, 0.18, 0.12);
        tone(1046.5, 0.9, 0.14, 0.25);
        break;
    }
  }, [stopVoices]);

  const toggle = useCallback(() => {
    const next = !wanted.current;
    wanted.current = next;
    const operation = ++generation.current;
    if (!next) {
      setEnabled(false);
      stopVoices();
      const ctx = context.current;
      if (ctx && ctx.state !== 'closed') void ctx.suspend().catch(() => undefined);
      return;
    }

    try {
      if (!context.current || context.current.state === 'closed') {
        const Constructor = audioConstructor();
        if (!Constructor) throw new Error('Web Audio unavailable');
        const ctx = new Constructor();
        const volume = ctx.createGain();
        volume.gain.value = 0.08;
        volume.connect(ctx.destination);
        context.current = ctx;
        master.current = volume;
      }
      const ctx = context.current;
      // This call stays in the click's user-activation stack.
      void ctx.resume().then(() => {
        if (!mounted.current || operation !== generation.current || !wanted.current || context.current !== ctx) return;
        if (document.hidden) {
          void ctx.suspend().catch(() => undefined);
          setEnabled(true);
          return;
        }
        setEnabled(true);
        renderCue('select', ctx);
      }).catch(() => {
        if (!mounted.current || operation !== generation.current) return;
        wanted.current = false;
        setEnabled(false);
      });
    } catch {
      wanted.current = false;
      setEnabled(false);
      setAvailable(false);
    }
  }, [renderCue, stopVoices]);

  const play = useCallback((cue: OrbitalAudioCue) => {
    const ctx = context.current;
    if (!wanted.current || !ctx || document.hidden || ctx.state === 'closed') return;
    if (ctx.state === 'running') {
      renderCue(cue, ctx);
      return;
    }
    // Returning to a tab never starts sound by itself; another user gesture does.
    if (!navigator.userActivation?.isActive) return;
    const operation = generation.current;
    void ctx.resume().then(() => {
      if (mounted.current && wanted.current && operation === generation.current && context.current === ctx) renderCue(cue, ctx);
    }).catch(() => undefined);
  }, [renderCue]);

  useEffect(() => {
    mounted.current = true;
    const onVisibility = () => {
      if (!document.hidden) return;
      stopVoices();
      const ctx = context.current;
      if (ctx && ctx.state !== 'closed') void ctx.suspend().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      mounted.current = false;
      wanted.current = false;
      generation.current++;
      document.removeEventListener('visibilitychange', onVisibility);
      stopVoices();
      const ctx = context.current;
      context.current = null;
      master.current?.disconnect();
      master.current = null;
      if (ctx && ctx.state !== 'closed') void ctx.close().catch(() => undefined);
    };
  }, [stopVoices]);

  return { enabled, available, toggle, play };
}
