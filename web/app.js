/* Kinora front end. Plain JavaScript, no build step.
 *
 * Layers:
 *   backend  – talks to the Kinora server (or a local stand-in for the static preview)
 *   player   – spoken replies and voice previews
 *   recorder – microphone capture for record-and-reply voice
 *   views    – home, companion details, conversation room, settings
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const uid = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '')
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join(''));

  // ---------------------------------------------------------------- settings
  const DEFAULT_SETTINGS = { readAloud: 'voice', replyLength: 'short', reviewTranscript: true, largeText: false, reduceMotion: false };
  function loadSettings() {
    try { return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem('kinora.settings') || '{}') }; }
    catch { return { ...DEFAULT_SETTINGS }; }
  }
  function saveSettings() {
    try { localStorage.setItem('kinora.settings', JSON.stringify(state.settings)); } catch { /* storage unavailable: settings last for this visit */ }
  }

  const state = {
    mode: null,                 // 'connected' | 'demo' | 'preview'
    companions: [],
    limits: { max_message_chars: 2000, max_recording_seconds: 60, max_audio_bytes: 5e6 },
    usage: null,
    settings: loadSettings(),
    session: null,              // { id, companion, messages, token, ended }
    status: 'idle',
    inflight: null,             // AbortController for the pending reply
    audioCtrl: null,            // AbortController for the pending voice download
    playingId: null,
    muted: false,
    composerSource: 'text',     // becomes 'voice' after a transcription lands in the box
  };

  class ApiError extends Error {
    constructor(code, message, status) { super(message); this.code = code; this.status = status; }
  }

  // ---------------------------------------------------------------- backends
  const serverBackend = {
    async request(path, { method = 'GET', json, form, signal, expect = 'json' } = {}) {
      const headers = { 'X-Kinora': '1' };
      let body;
      if (json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
      if (form) body = form;
      let res;
      try {
        res = await fetch(path, { method, headers, body, signal, credentials: 'same-origin' });
      } catch (e) {
        if (e.name === 'AbortError') throw e;
        throw new ApiError('network', "Kinora can't reach its server. Check that it's still running and your connection is working, then try again.");
      }
      const type = res.headers.get('content-type') || '';
      if (!res.ok) {
        if (type.includes('json')) {
          const data = await res.json().catch(() => ({}));
          if (data.error) throw new ApiError(data.error.code, data.error.message, res.status);
        }
        throw new ApiError('http_' + res.status, 'Something went wrong on the server. Try again.', res.status);
      }
      if (expect === 'blob') return res.blob();
      if (!type.includes('json')) throw new ApiError('bad_response', 'The server sent an unexpected response.');
      return res.json();
    },
    init() { return this.request('/api/config'); },
    access(code) { return this.request('/api/access', { method: 'POST', json: { code } }); },
    startSession(companionId) { return this.request('/api/sessions', { method: 'POST', json: { companion_id: companionId } }); },
    send(sessionId, payload, signal) { return this.request(`/api/sessions/${sessionId}/messages`, { method: 'POST', json: payload, signal }); },
    transcribe(sessionId, blob, durationMs, signal) {
      const form = new FormData();
      const ext = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('mpeg') ? 'mp3' : 'webm';
      form.append('audio', blob, `voice.${ext}`);
      form.append('duration_ms', String(Math.round(durationMs)));
      return this.request(`/api/sessions/${sessionId}/transcribe`, { method: 'POST', form, signal });
    },
    speech(sessionId, messageId, signal) {
      return this.request(`/api/sessions/${sessionId}/speech`, { method: 'POST', json: { message_id: messageId }, signal, expect: 'blob' });
    },
    endSession(sessionId) { return this.request(`/api/sessions/${sessionId}`, { method: 'DELETE' }); },
    voicePreview(companionId) { return this.request(`/api/companions/${companionId}/voice-preview`, { expect: 'blob' }); },
    usage() { return this.request('/api/usage'); },
  };

  // Static interface preview: no server, fixed placeholder replies.
  const DEMO_REPLIES = [
    'This is a demo reply, not a real AI response. In connected mode, your companion would respond to the specific things you just wrote.',
    'Demo mode is on, so this text is fixed. Once an OpenAI API key is added, your companion will listen and reply to what you actually said.',
    'Still a demo reply. The buttons, transcript and controls all work. Only the words here are placeholders.',
  ];
  const wait = (ms, signal) => new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')); });
  });
  const previewBackend = {
    turn: 0,
    async init() { return { mode: 'preview', companions: window.KINORA_PREVIEW.companions, limits: window.KINORA_PREVIEW.limits, usage: null }; },
    async startSession(companionId) {
      const c = state.companions.find((x) => x.id === companionId);
      return { session_id: 'preview-' + uid(), messages: [{ id: uid(), role: 'assistant', content: c.opening, demo: false }] };
    },
    async send(sessionId, payload, signal) {
      await wait(900, signal);
      return {
        user_message: { id: uid(), role: 'user', content: payload.text },
        reply: { id: uid(), role: 'assistant', content: DEMO_REPLIES[this.turn++ % DEMO_REPLIES.length], demo: true },
      };
    },
    async transcribe(sessionId, blob, durationMs, signal) {
      await wait(700, signal);
      return { text: "(Demo transcription. Speech-to-text isn't connected yet, so edit this text before sending.)", demo: true };
    },
    async speech() { throw new ApiError('voice_demo', "AI voice isn't connected in demo mode."); },
    async endSession() { return { ok: true }; },
    async voicePreview() { throw new ApiError('voice_demo', "AI voice isn't connected in demo mode."); },
    async usage() { return null; },
  };

  let backend = serverBackend;

  // ---------------------------------------------------------------- status
  const STATUS_TEXT = {
    idle: 'Ready',
    recording: 'Recording. Microphone is on',
    transcribing: 'Turning your recording into text…',
    thinking: 'Writing a reply…',
    preparing: 'Getting the voice ready…',
    speaking: 'Speaking',
    'speaking-demo': "Speaking with your browser's built-in voice (demo)",
    error: 'Something went wrong',
  };
  function setStatus(status, text) {
    state.status = status;
    const box = $('status');
    box.dataset.state = status === 'speaking-demo' ? 'speaking' : status;
    $('status-text').textContent = text || STATUS_TEXT[status] || status;
    updateControls();
  }
  const busy = () => ['recording', 'transcribing', 'thinking'].includes(state.status);

  function updateControls() {
    const s = state.session;
    const live = s && !s.ended;
    const speaking = ['speaking', 'speaking-demo', 'preparing'].includes(state.status);
    $('btn-stop').disabled = !speaking;
    $('btn-replay').disabled = !live || !lastReply() || busy();
    $('btn-send').disabled = !live || ['recording', 'transcribing', 'thinking'].includes(state.status);
    $('btn-mic').disabled = !live || ['transcribing', 'thinking'].includes(state.status);
    $('message').disabled = !live || state.status === 'recording';
    $('btn-mute').setAttribute('aria-pressed', String(state.muted));
    $('mute-label').textContent = state.muted ? 'Voice muted' : 'Mute voice';
    $('mute-wave').style.display = state.muted ? 'none' : '';
  }

  // ---------------------------------------------------------------- transcript
  const nodes = new WeakMap(); // message object -> <li>
  let typingNode = null;

  function companionOf(session) { return session ? session.companion : null; }
  function lastReply() {
    const s = state.session;
    return s && [...s.messages].reverse().find((m) => m.role === 'assistant' && m.status !== 'typing');
  }

  function renderMessage(msg) {
    let li = nodes.get(msg);
    const fresh = !li;
    if (fresh) { li = el('li'); nodes.set(msg, li); }
    li.className = `msg ${msg.role}${msg.status === 'pending' ? ' pending' : ''}`;
    li.replaceChildren();

    const who = el('div', 'who', msg.role === 'assistant' ? companionOf(state.session).name : 'You');
    if (msg.role === 'user' && msg.source === 'voice') who.append(el('span', null, '· from voice'));
    if (msg.role === 'user' && msg.status === 'pending') who.append(el('span', null, '· sending'));
    if (msg.demo) who.append(el('span', 'demo-tag', 'Demo reply · not AI'));
    li.append(who, el('div', 'bubble', msg.content));

    const tools = el('div', 'msg-tools');
    if (msg.role === 'assistant') {
      const playing = state.playingId === msg.id;
      const play = el('button', 'btn', playing ? (state.status === 'preparing' ? 'Getting voice…' : 'Playing') : 'Play');
      play.type = 'button';
      play.disabled = playing;
      play.setAttribute('aria-label', `Play this reply aloud`);
      play.addEventListener('click', () => playReply(msg));
      tools.append(play);
      if (msg.voiceError) {
        const err = el('span', 'msg-error', msg.voiceError);
        tools.append(err);
      }
    }
    if (msg.role === 'user' && msg.status === 'failed') {
      tools.append(el('span', 'msg-error', msg.error));
      const retry = el('button', 'btn', 'Try again');
      retry.type = 'button';
      retry.addEventListener('click', () => deliver(msg));
      const edit = el('button', 'btn quiet', 'Edit');
      edit.type = 'button';
      edit.addEventListener('click', () => {
        removeMessage(msg);
        $('message').value = msg.content;
        state.composerSource = msg.source;
        autosize(); $('message').focus();
      });
      tools.append(retry, edit);
    }
    if (tools.childNodes.length) li.append(tools);

    if (fresh) {
      $('transcript').insertBefore(li, typingNode && typingNode.isConnected ? typingNode : null);
      scrollToEnd();
    }
  }
  function removeMessage(msg) {
    const s = state.session;
    s.messages = s.messages.filter((m) => m !== msg);
    nodes.get(msg)?.remove();
  }
  function showTyping(on) {
    if (on) {
      if (!typingNode) {
        typingNode = el('li', 'msg assistant pending');
        const bubble = el('div', 'bubble', 'Writing a reply');
        const dots = el('span', 'typing-dots');
        dots.setAttribute('aria-hidden', 'true');
        dots.append(el('i'), el('i'), el('i'));
        bubble.append(dots);
        typingNode.append(el('div', 'who', companionOf(state.session).name), bubble);
      }
      $('transcript').append(typingNode);
      scrollToEnd();
    } else typingNode?.remove();
  }
  function scrollToEnd() {
    const t = $('transcript');
    t.scrollTop = t.scrollHeight;
  }
  function refreshAssistantTools() {
    state.session?.messages.filter((m) => m.role === 'assistant').forEach(renderMessage);
  }

  // ---------------------------------------------------------------- composer
  function showComposerError(message, action) {
    const box = $('composer-error');
    box.replaceChildren(el('span', null, message));
    if (action) {
      const b = el('button', 'btn', action.label);
      b.type = 'button';
      b.addEventListener('click', action.run);
      box.append(b);
    }
    box.hidden = false;
  }
  function hideComposerError() { $('composer-error').hidden = true; }
  function setHint(text) { $('composer-hint').textContent = text || ''; $('composer-hint').hidden = !text; }

  function autosize() {
    const t = $('message');
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight + 2, 180) + 'px';
    const max = state.limits.max_message_chars;
    const n = t.value.length;
    $('char-count').textContent = n > max * 0.8 ? `${n} / ${max}` : '';
  }

  async function sendText(rawText, source) {
    const s = state.session;
    if (!s || s.ended || busy()) return;     // ignores repeated clicks while a reply is pending
    const text = rawText.trim();
    if (!text) { showComposerError('Type or record a message first.'); return; }
    if (text.length > state.limits.max_message_chars) {
      showComposerError(`Messages can be up to ${state.limits.max_message_chars} characters. Try splitting it up.`);
      return;
    }
    stopPlayback();
    const msg = { id: null, clientId: uid(), role: 'user', content: text, status: 'pending', source };
    s.messages.push(msg);
    renderMessage(msg);
    $('message').value = '';
    state.composerSource = 'text';
    setHint('');
    autosize();
    await deliver(msg);
  }

  async function deliver(msg) {
    const s = state.session;
    if (!s || s.ended || busy()) return;
    const token = s.token;
    const ctrl = new AbortController();
    state.inflight = ctrl;
    msg.status = 'pending';
    renderMessage(msg);
    hideComposerError();
    setStatus('thinking');
    showTyping(true);
    try {
      const res = await backend.send(s.id, {
        client_message_id: msg.clientId, text: msg.content, reply_length: state.settings.replyLength,
      }, ctrl.signal);
      if (!isCurrent(token)) return;          // conversation ended or replaced while waiting
      showTyping(false);
      msg.status = 'sent';
      msg.id = res.user_message.id;
      renderMessage(msg);
      const reply = { ...res.reply, status: 'sent' };
      s.messages.push(reply);
      renderMessage(reply);
      if (res.usage) applyUsage(res.usage);
      setStatus('idle');
      if (shouldSpeak(msg.source)) playReply(reply);
    } catch (e) {
      if (e.name === 'AbortError' || !isCurrent(token)) return;
      showTyping(false);
      if (e.code === 'session_not_found') { sessionGone(); return; }
      msg.status = 'failed';
      msg.error = e.message;
      renderMessage(msg);
      setStatus('error', e.code === 'rate_limited' || e.code?.endsWith('budget') ? 'Limit reached' : 'Reply failed');
    } finally {
      if (state.inflight === ctrl) state.inflight = null;
      updateControls();
    }
  }

  const isCurrent = (token) => state.session && state.session.token === token && !state.session.ended;
  const shouldSpeak = (source) => !state.muted && (state.settings.readAloud === 'always' || (state.settings.readAloud === 'voice' && source === 'voice'));

  // ---------------------------------------------------------------- playback
  const audio = new Audio();
  audio.preload = 'auto';
  audio.addEventListener('ended', finishPlayback);
  audio.addEventListener('error', () => {
    if (!state.playingId || !audio.getAttribute('src')) return;
    const msg = state.session?.messages.find((m) => m.id === state.playingId);
    if (msg) { msg.voiceError = "The audio couldn't be played. Try Play again."; }
    finishPlayback();
  });

  function finishPlayback() {
    state.playingId = null;
    if (['speaking', 'speaking-demo', 'preparing'].includes(state.status)) setStatus('idle');
    refreshAssistantTools();
    updateControls();
  }

  function stopPlayback() {
    state.audioCtrl?.abort();
    state.audioCtrl = null;
    audio.pause();
    try { audio.currentTime = 0; } catch { /* nothing loaded */ }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    if (state.playingId) finishPlayback();
  }

  async function playReply(msg) {
    const s = state.session;
    if (!s || s.ended) return;
    stopPlayback();
    const token = s.token;
    msg.voiceError = null;
    state.playingId = msg.id;
    try {
      if (!msg.audioUrl) {
        setStatus('preparing');
        renderMessage(msg);
        const ctrl = new AbortController();
        state.audioCtrl = ctrl;
        const blob = await backend.speech(s.id, msg.id, ctrl.signal);
        if (!isCurrent(token) || state.playingId !== msg.id) return;
        msg.audioUrl = URL.createObjectURL(blob);
      }
      audio.src = msg.audioUrl;
      setStatus('speaking');
      renderMessage(msg);
      await audio.play();
    } catch (e) {
      if (e.name === 'AbortError' || !isCurrent(token) || state.playingId !== msg.id) return;
      if (e.code === 'voice_demo') {
        if (speakWithBrowser(msg)) return;
        msg.voiceError = "AI voice isn't connected in demo mode, and this browser has no built-in voice.";
      } else if (e.name === 'NotAllowedError') {
        msg.voiceError = 'Your browser blocked automatic playback. Press Play to hear this reply.';
      } else {
        msg.voiceError = (e.message || "The voice reply couldn't be created.") + ' The text reply is above.';
      }
      finishPlayback();
    }
  }

  // Demo only: the browser's built-in speech, clearly labelled. It is not the companion's AI voice.
  function speakWithBrowser(msg) {
    if (!('speechSynthesis' in window) || !window.SpeechSynthesisUtterance) return false;
    const u = new SpeechSynthesisUtterance(msg.content);
    u.rate = 0.95;
    u.onend = finishPlayback;
    u.onerror = finishPlayback;
    setStatus('speaking-demo');
    renderMessage(msg);
    window.speechSynthesis.speak(u);
    return true;
  }

  // ---------------------------------------------------------------- recording
  const rec = { stream: null, recorder: null, chunks: [], started: 0, ctx: null, analyser: null, raf: 0, peak: 0, cancelled: false, token: null, mime: '' };

  function pickMime() {
    if (!window.MediaRecorder) return null;
    // These are formats the transcription service accepts. Ogg isn't one of them.
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/mpeg'].find((m) => MediaRecorder.isTypeSupported(m)) || null;
  }

  async function startRecording() {
    const s = state.session;
    if (!s || s.ended || busy()) return;
    hideComposerError();
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      showComposerError("This browser can't record audio here. You can still type your message.");
      return;
    }
    const mime = pickMime();
    if (!mime) {
      showComposerError("This browser records audio in a format Kinora can't use. Try Chrome, Edge, Firefox or Safari, or type instead.");
      return;
    }
    stopPlayback();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      const msg = e.name === 'NotAllowedError' || e.name === 'SecurityError'
        ? 'Microphone access is blocked. To record, allow the microphone in your browser\'s site settings. Typing still works.'
        : e.name === 'NotFoundError'
          ? 'No microphone was found. Connect one and try again, or type instead.'
          : "The microphone couldn't start. Close other apps that might be using it, or type instead.";
      showComposerError(msg);
      return;
    }
    if (!isCurrent(s.token)) { stream.getTracks().forEach((t) => t.stop()); return; }

    Object.assign(rec, { stream, chunks: [], peak: 0, cancelled: false, token: s.token, mime });
    rec.recorder = new MediaRecorder(stream, { mimeType: mime });
    rec.recorder.ondataavailable = (e) => { if (e.data && e.data.size) rec.chunks.push(e.data); };
    rec.recorder.onstop = onRecordingStopped;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      rec.ctx = new Ctx();
      rec.analyser = rec.ctx.createAnalyser();
      rec.analyser.fftSize = 1024;
      rec.ctx.createMediaStreamSource(stream).connect(rec.analyser);
    } catch { rec.ctx = null; rec.analyser = null; }

    rec.started = performance.now();
    rec.recorder.start(250);
    $('btn-mic').setAttribute('aria-pressed', 'true');
    $('mic-label').textContent = 'Stop recording';
    $('rec-meter').hidden = !rec.analyser;
    $('rec-timer').hidden = false;
    setStatus('recording');
    tickRecording();
  }

  function tickRecording() {
    const elapsed = (performance.now() - rec.started) / 1000;
    const max = state.limits.max_recording_seconds;
    const left = Math.max(0, Math.ceil(max - elapsed));
    $('rec-timer').textContent = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')}`;
    $('rec-timer').setAttribute('aria-label', `Recording, ${left} seconds left`);
    if (rec.analyser) {
      const buf = new Float32Array(rec.analyser.fftSize);
      rec.analyser.getFloatTimeDomainData(buf);
      const rms = Math.sqrt(buf.reduce((sum, v) => sum + v * v, 0) / buf.length);
      rec.peak = Math.max(rec.peak, rms);
      $('rec-level').style.width = Math.min(100, rms * 400) + '%';
    }
    if (elapsed >= max) { stopRecording(false); setHint(`Recordings stop automatically after ${max} seconds.`); return; }
    rec.raf = requestAnimationFrame(tickRecording);
  }

  function stopRecording(cancel) {
    if (!rec.recorder) return;
    rec.cancelled = cancel;
    cancelAnimationFrame(rec.raf);
    if (rec.recorder.state !== 'inactive') rec.recorder.stop();
    rec.stream?.getTracks().forEach((t) => t.stop());   // microphone is actually off from here
    rec.ctx?.close().catch(() => {});
    $('btn-mic').setAttribute('aria-pressed', 'false');
    $('mic-label').textContent = 'Record';
    $('rec-meter').hidden = true;
    $('rec-timer').hidden = true;
    if (state.status === 'recording') setStatus('idle');
  }

  async function onRecordingStopped() {
    const durationMs = performance.now() - rec.started;
    const blob = new Blob(rec.chunks, { type: rec.mime.split(';')[0] });
    const { cancelled, token, analyser, peak } = rec;
    rec.recorder = null; rec.chunks = []; rec.stream = null;
    if (cancelled || !isCurrent(token)) return;
    if (durationMs < 800 || blob.size < 1000) {
      showComposerError('That recording was too short. Press Record, speak, then press Stop recording.');
      return;
    }
    if (analyser && peak < 0.01) {
      showComposerError("Kinora couldn't hear anything. Check that the right microphone is selected and try again, or type instead.");
      return;
    }
    if (blob.size > state.limits.max_audio_bytes) {
      showComposerError('That recording is too large. Keep voice messages under a minute.');
      return;
    }
    const s = state.session;
    const ctrl = new AbortController();
    state.inflight = ctrl;
    setStatus('transcribing');
    try {
      const res = await backend.transcribe(s.id, blob, durationMs, ctrl.signal);
      if (!isCurrent(token)) return;
      setStatus('idle');
      if (state.settings.reviewTranscript || res.demo) {
        const box = $('message');
        box.value = box.value.trim() ? box.value.trim() + ' ' + res.text : res.text;
        state.composerSource = 'voice';
        autosize();
        setHint(res.demo
          ? "Demo mode: speech-to-text isn't connected, so this is placeholder text. Edit it, then press Send."
          : 'Here is what Kinora heard. Fix anything that is wrong, then press Send.');
        box.focus();
      } else {
        await sendText(res.text, 'voice');
      }
    } catch (e) {
      if (e.name === 'AbortError' || !isCurrent(token)) return;
      if (e.code === 'session_not_found') { sessionGone(); return; }
      setStatus('error', 'Transcription failed');
      showComposerError(e.message + ' Your recording was not kept, so please record again or type instead.');
    } finally {
      if (state.inflight === ctrl) state.inflight = null;
      updateControls();
    }
  }

  // ---------------------------------------------------------------- sessions
  async function startSession(companion) {
    if (state.session && !state.session.ended && state.session.companion.id === companion.id) { go('room'); return; }
    if (state.session && !state.session.ended) await endSession({ silent: true });
    try {
      const res = await backend.startSession(companion.id);
      state.session = {
        id: res.session_id, companion, token: uid(), ended: false,
        messages: res.messages.map((m) => ({ ...m, status: 'sent' })),
      };
    } catch (e) {
      showBanner(e.message, 'warn');
      return;
    }
    $('transcript').replaceChildren();
    typingNode = null;
    state.session.messages.forEach(renderMessage);
    $('ended').hidden = true;
    $('composer').hidden = false;
    $('end-confirm').hidden = true;
    hideComposerError();
    setHint('');
    setStatus('idle');
    go('room');
  }

  async function endSession({ silent = false } = {}) {
    const s = state.session;
    if (!s || s.ended) return;
    s.ended = true;                       // from here, late responses for this session are ignored
    state.inflight?.abort();
    stopRecording(true);
    stopPlayback();
    s.messages.forEach((m) => m.audioUrl && URL.revokeObjectURL(m.audioUrl));
    s.messages = [];
    backend.endSession(s.id).catch(() => { /* already gone on the server */ });
    $('transcript').replaceChildren();
    typingNode = null;
    $('message').value = '';
    autosize();
    setHint('');
    hideComposerError();
    $('end-confirm').hidden = true;
    if (!silent) {
      $('composer').hidden = true;
      $('ended').hidden = false;
      setStatus('idle', 'Conversation ended');
      $('ended').querySelector('h2').setAttribute('tabindex', '-1');
      $('ended').querySelector('h2').focus();
    }
    renderContinue();
  }

  function sessionGone() {
    showBanner('That conversation expired after being idle, so Kinora cleared it. Start a new one whenever you like.', 'info');
    endSession();
  }

  // ---------------------------------------------------------------- views
  const VIEWS = ['home', 'details', 'room'];
  function go(hash) { if (location.hash !== '#' + hash) location.hash = hash; else route(); }

  function route() {
    const hash = location.hash.replace('#', '') || 'home';
    let view = 'home';
    if (hash.startsWith('companion-')) {
      const c = state.companions.find((x) => 'companion-' + x.id === hash);
      if (c) { renderDetails(c); view = 'details'; }
    } else if (hash === 'room' && state.session && (!state.session.ended || !$('ended').hidden)) {
      view = 'room';
    }
    if (view !== 'room' && state.status === 'recording') stopRecording(true);
    if (view !== 'room') stopPlayback();
    VIEWS.forEach((v) => { $('view-' + v).hidden = v !== view; });
    document.body.classList.toggle('in-room', view === 'room');
    document.body.classList.toggle('in-details', view === 'details');
    if (view === 'home') renderContinue();
    if (view === 'room') renderRoomHeader();
    const heading = $('view-' + view).querySelector('h1');
    heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  const ARROW = '<svg aria-hidden="true" viewBox="0 0 24 24" class="icon arrow"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

  function renderHome() {
    const companions = state.companions.filter((c) => c.available);

    // Hero portraits
    $('hero-faces').replaceChildren(...state.companions.slice(0, 3).map((c) => {
      const face = el('div', `face accent-${c.accent}`);
      const img = el('img');
      img.src = c.portrait; img.alt = '';
      face.append(img);
      return face;
    }));

    // Ticker of example situations (duplicated once so the loop is seamless)
    const phrases = state.companions.flatMap((c) => c.situations || []);
    $('ticker').replaceChildren(...[...phrases, ...phrases].map((p) => el('span', null, `“${p}”`)));

    // Situation cards: one tap starts the matching companion
    $('intent-list').replaceChildren(...companions.flatMap((c) => (c.situations || []).slice(0, 2).map((s, i) => {
      const li = el('li', 'reveal');
      li.style.setProperty('--rd', `${i * 90}ms`);
      const b = el('button', `intent-card accent-${c.accent}`);
      b.type = 'button';
      b.append(el('span', 'intent-q', `“${s}”`));
      const to = el('span', 'intent-to');
      const img = el('img'); img.src = c.portrait; img.alt = '';
      const label = el('span');
      label.append('Talk with ', el('b', null, c.name));
      to.append(img, label);
      to.insertAdjacentHTML('beforeend', ARROW);
      b.append(to);
      b.setAttribute('aria-label', `${s}. Start a conversation with ${c.name}, ${c.role.toLowerCase()}`);
      b.addEventListener('click', () => startSession(c));
      li.append(b);
      return li;
    })));

    // Companion showcase
    const list = $('companion-list');
    list.replaceChildren();
    state.companions.forEach((c) => {
      const li = el('li', `panel reveal accent-${c.accent}`);
      li.id = 'panel-' + c.id;

      const media = el('div', 'panel-media');
      media.append(el('span', 'halo'), el('span', 'ring'));
      const arch = el('div', 'arch xl');
      const img = el('img');
      img.src = c.portrait; img.alt = c.portrait_alt; img.loading = 'lazy';
      img.dataset.parallax = '';
      arch.append(img);
      media.append(arch);

      const copy = el('div', 'panel-copy');
      copy.append(el('p', 'kicker', c.role));
      const head = el('div', 'panel-head');
      head.append(el('h3', 'panel-name', c.name));
      copy.append(head, el('p', 'panel-desc', c.description));
      const traits = el('ul', 'traits');
      c.style.forEach((s) => traits.append(el('li', null, s)));
      copy.append(traits, el('blockquote', 'quote', `“${c.opening}”`));
      const meta = el('div', 'panel-meta');
      meta.append(el('span', null, 'AI companion'), el('span', null, `AI voice · ${c.voice.label.toLowerCase()}`));
      copy.append(meta);

      if (c.available) {
        const actions = el('div', 'panel-actions');
        const start = el('button', 'btn primary large');
        start.type = 'button';
        start.innerHTML = ARROW;
        start.prepend(`Talk with ${c.name}`);
        start.addEventListener('click', () => startSession(c));
        const about = el('a', 'btn ghost large', `About ${c.name}`);
        about.href = '#companion-' + c.id;
        actions.append(start, about);
        if (state.mode === 'connected') actions.append(previewButton(c, true));
        copy.append(actions);
      } else {
        copy.append(el('p', 'muted', c.available_note || 'Not available yet'));
      }
      li.append(media, copy);
      list.append(li);
    });
    observeReveals();
  }

  // ---------------------------------------------------------------- motion
  const prefersReduced = () => state.settings.reduceMotion || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let revealObserver = null;

  function initMotion() {
    const root = document.documentElement;
    if (!prefersReduced() && 'IntersectionObserver' in window) {
      root.classList.add('motion');
      revealObserver = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); revealObserver.unobserve(e.target); } });
      }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
      // Safety net: never leave content hidden if the observer doesn't fire.
      setTimeout(() => document.querySelectorAll('.reveal:not(.in)').forEach((n) => {
        const r = n.getBoundingClientRect();
        if (r.top < window.innerHeight) n.classList.add('in');
      }), 2500);
    }

    // Header gains a glass background once you scroll.
    const onScroll = () => {
      $('topbar').classList.toggle('scrolled', window.scrollY > 12);
      if (!prefersReduced() && !$('view-home').hidden) parallax();
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    // Soft glow follows the pointer across situation cards.
    document.addEventListener('pointermove', (e) => {
      const card = e.target.closest?.('.intent-card');
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${e.clientX - r.left}px`);
      card.style.setProperty('--my', `${e.clientY - r.top}px`);
    }, { passive: true });

    document.querySelectorAll('[data-scroll]').forEach((b) => b.addEventListener('click', () => {
      if ($('view-home').hidden) go('home');
      requestAnimationFrame(() => $(b.dataset.scroll)?.scrollIntoView({ behavior: prefersReduced() ? 'auto' : 'smooth', block: 'start' }));
    }));
  }

  function observeReveals() {
    if (!revealObserver) return;
    document.querySelectorAll('.reveal:not(.in)').forEach((n) => revealObserver.observe(n));
  }

  let parallaxQueued = false;
  function parallax() {
    if (parallaxQueued) return;
    parallaxQueued = true;
    requestAnimationFrame(() => {
      parallaxQueued = false;
      const vh = window.innerHeight;
      document.querySelectorAll('[data-parallax]').forEach((img) => {
        const r = img.parentElement.getBoundingClientRect();
        if (r.bottom < 0 || r.top > vh) return;
        const progress = (r.top + r.height / 2 - vh / 2) / vh; // -1 … 1
        img.style.translate = `0 ${(progress * -28).toFixed(1)}px`;
      });
    });
  }

  function renderContinue() {
    const s = state.session;
    const show = s && !s.ended;
    $('continue-area').hidden = !show;
    if (!show) return;
    $('continue-portrait').src = s.companion.portrait;
    // Deliberately no excerpt of the conversation here.
    $('continue-text').textContent = `You have a conversation with ${s.companion.name} open.`;
  }

  function renderDetails(c) {
    $('details-portrait').src = c.portrait;
    $('details-portrait').alt = c.portrait_alt;
    $('details-name').textContent = c.name;
    $('details-role').textContent = c.role;
    $('details-role').parentElement.className = `details-body accent-${c.accent}`;
    $('details-purpose').textContent = c.purpose;
    $('details-style').replaceChildren(...c.style.map((s) => el('li', null, s)));
    $('details-opening').textContent = c.opening;
    $('details-scope').textContent = c.scope;
    $('details-voice').textContent = state.mode === 'connected'
      ? `AI-generated voice: ${c.voice.label.toLowerCase()}.`
      : `AI-generated voice: ${c.voice.label.toLowerCase()}. The preview plays once an OpenAI API key is connected.`;
    const btn = $('details-preview');
    btn.hidden = state.mode !== 'connected';
    btn.onclick = () => playPreview(c, $('details-preview-msg'), btn);
    $('details-preview-msg').textContent = '';
    const start = $('details-start');
    start.disabled = !c.available;
    start.textContent = c.available ? `Start a conversation with ${c.name}` : (c.available_note || 'Not available yet');
    start.onclick = () => startSession(c);
  }

  function previewButton(c, compact) {
    const b = el('button', compact ? 'btn ghost large' : 'btn ghost');
    b.type = 'button';
    b.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" class="icon"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 010 7"/></svg>';
    b.append(compact ? 'Hear voice' : 'Play voice preview');
    b.setAttribute('aria-label', `Play a short preview of ${c.name}'s AI voice`);
    b.addEventListener('click', () => playPreview(c, null, b));
    return b;
  }

  let previewUrlCache = {};
  async function playPreview(c, msgEl, button) {
    stopPlayback();
    button.disabled = true;
    if (msgEl) msgEl.textContent = 'Loading preview…';
    try {
      if (!previewUrlCache[c.id]) previewUrlCache[c.id] = URL.createObjectURL(await backend.voicePreview(c.id));
      audio.src = previewUrlCache[c.id];
      await audio.play();
      if (msgEl) msgEl.textContent = 'Playing preview.';
    } catch (e) {
      const text = e.name === 'NotAllowedError' ? 'Your browser blocked playback. Try the button again.' : e.message;
      if (msgEl) msgEl.textContent = text; else showBanner(text, 'warn');
    } finally {
      button.disabled = false;
    }
  }

  function renderRoomHeader() {
    const c = state.session.companion;
    $('room-portrait').src = c.portrait;
    $('room-portrait').alt = c.portrait_alt;
    $('room-name').textContent = c.name;
    $('room-role').textContent = c.role;
    $('room-role').className = `role accent-${c.accent}`;
    $('view-room').className = `view room accent-${c.accent}`;
    $('message-label').textContent = `Message to ${c.name}`;
    updateControls();
  }

  // ---------------------------------------------------------------- banner, usage, mode
  let modeBannerText = '';
  function showBanner(text, kind) {
    const b = $('banner');
    b.textContent = text;
    b.className = 'banner' + (kind === 'info' ? ' info' : '');
    b.hidden = !text;
  }
  function applyUsage(usage) {
    state.usage = usage;
    if (usage && usage.warning) showBanner(usage.warning, 'warn');
    else showBanner(modeBannerText, 'warn');
    renderUsage();
  }
  function renderUsage() {
    const dl = $('usage-list');
    dl.replaceChildren();
    const u = state.usage;
    if (!u) { dl.append(el('dt', null, 'Usage tracking'), el('dd', null, 'Not available in this preview')); return; }
    const rows = [
      ['Messages', u.used.replies, u.limits.replies, ''],
      ['Voice recording', Math.round(u.used.audio_seconds / 6) / 10, Math.round(u.limits.audio_seconds / 60), ' min'],
      ['Spoken replies', u.used.tts_chars.toLocaleString(), u.limits.tts_chars.toLocaleString(), ' characters'],
    ];
    rows.forEach(([label, used, limit, unit]) => dl.append(el('dt', null, label), el('dd', null, `${used} of ${limit}${unit}`)));
  }

  function applyMode() {
    const badge = $('mode-badge');
    badge.hidden = false;
    badge.className = 'mode-badge' + (state.mode === 'connected' ? ' connected' : '');
    badge.textContent = { connected: 'Connected', demo: 'Demo mode', preview: 'Interface preview' }[state.mode];
    modeBannerText = {
      connected: '',
      demo: "Demo mode: no OpenAI API key is set, so replies are fixed placeholder text, not AI, and AI voice is off. Everything else works. See README.md to connect.",
      preview: 'Interface preview: a static copy with no server. Replies are placeholder text, not AI, and recording usually isn\'t available here.',
    }[state.mode];
    showBanner(modeBannerText, 'warn');
    if (state.mode !== 'connected') {
      $('data-note').textContent = state.mode === 'preview'
        ? 'This preview runs entirely in your browser and sends nothing anywhere. There are no accounts, so there is no account to delete.'
        : 'In demo mode nothing is sent to OpenAI. There are no accounts yet, so there is no account to delete.';
    }
  }

  // ---------------------------------------------------------------- settings dialog
  function applySettings() {
    const root = document.documentElement;
    root.classList.toggle('large-text', state.settings.largeText);
    root.classList.toggle('reduce-motion', state.settings.reduceMotion);
  }
  function bindSettings() {
    const s = state.settings;
    document.querySelectorAll('input[name="readAloud"]').forEach((r) => {
      r.checked = r.value === s.readAloud;
      r.addEventListener('change', () => { s.readAloud = r.value; saveSettings(); });
    });
    document.querySelectorAll('input[name="replyLength"]').forEach((r) => {
      r.checked = r.value === s.replyLength;
      r.addEventListener('change', () => { s.replyLength = r.value; saveSettings(); });
    });
    [['review-transcript', 'reviewTranscript'], ['large-text', 'largeText'], ['reduce-motion', 'reduceMotion']].forEach(([id, key]) => {
      $(id).checked = s[key];
      $(id).addEventListener('change', () => { s[key] = $(id).checked; saveSettings(); applySettings(); });
    });
    $('open-settings').addEventListener('click', async () => {
      if (state.mode !== 'preview') {
        try { applyUsage(await backend.usage()); } catch { /* keep last known numbers */ }
      }
      renderUsage();
      const dlg = $('settings');
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    });
  }

  // ---------------------------------------------------------------- wiring
  function bindRoom() {
    $('composer').addEventListener('submit', (e) => { e.preventDefault(); sendText($('message').value, state.composerSource); });
    $('message').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); }
    });
    $('message').addEventListener('input', () => {
      autosize();
      if (!$('message').value.trim()) { state.composerSource = 'text'; setHint(''); }
    });
    $('btn-mic').addEventListener('click', () => (state.status === 'recording' ? stopRecording(false) : startRecording()));
    $('btn-stop').addEventListener('click', stopPlayback);
    $('btn-replay').addEventListener('click', () => { const r = lastReply(); if (r) playReply(r); });
    $('btn-mute').addEventListener('click', () => {
      state.muted = !state.muted;
      if (state.muted) stopPlayback();
      updateControls();
    });
    $('btn-home').addEventListener('click', () => go('home'));
    $('btn-end').addEventListener('click', () => { $('end-confirm').hidden = false; $('end-yes').focus(); });
    $('end-no').addEventListener('click', () => { $('end-confirm').hidden = true; $('btn-end').focus(); });
    $('end-yes').addEventListener('click', () => endSession());
    $('ended-new').addEventListener('click', () => startSession(state.session.companion));
    $('continue-btn').addEventListener('click', () => go('room'));
    $('continue-end').addEventListener('click', () => endSession({ silent: true }));
    document.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || $('view-room').hidden || $('settings').open) return;
      if (state.status === 'recording') { stopRecording(true); setHint('Recording discarded.'); }
      else stopPlayback();
    });
    window.addEventListener('hashchange', route);
  }

  // Resolves once the server accepts the code. The dialog can't be dismissed without one.
  function askForAccessCode() {
    return new Promise((resolve) => {
      const dlg = $('access');
      dlg.addEventListener('cancel', (e) => e.preventDefault());
      $('access-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const code = $('access-code').value.trim();
        if (!code) return;
        $('access-error').hidden = true;
        try {
          await backend.access(code);
          dlg.close();
          resolve();
        } catch (err) {
          $('access-error').textContent = err.message;
          $('access-error').hidden = false;
        }
      });
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
      $('access-code').focus();
    });
  }

  async function boot() {
    applySettings();
    bindSettings();
    bindRoom();
    initMotion();
    if (window.KINORA_PREVIEW) backend = previewBackend;
    let config;
    try {
      config = await backend.init();
    } catch (e) {
      showBanner(e.message || "Kinora couldn't start. Make sure the server is running, then reload.", 'warn');
      return;
    }
    if (config.access_required) await askForAccessCode();
    state.mode = config.mode;
    state.companions = config.companions;
    state.limits = { ...state.limits, ...config.limits };
    applyMode();
    if (config.usage) applyUsage(config.usage);
    renderHome();
    updateControls();
    route();
  }

  boot();
})();
