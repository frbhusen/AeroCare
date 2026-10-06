// Speech-to-Text Voice Dictation for Clinical Notes (Arabic & English)
// Uses native browser Web Speech API (SpeechRecognition / webkitSpeechRecognition).
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { toast } from "./modal.js";
import { icon } from "./icons.js";

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

/**
 * Creates a voice dictation button attached to a textarea.
 * @param {HTMLTextAreaElement} textarea - Target textarea to write into
 * @param {Object} [opts] - Options
 * @returns {HTMLButtonElement|null} - Button element or null if speech recognition is unsupported
 */
export function dictateButton(textarea, opts = {}) {
  if (!SpeechRecognition) return null;

  let recognition = null;
  let listening = false;

  const btn = h("button", {
    class: "dictate-trigger-btn",
    type: "button",
    title: t("core.dictate.title", { default: "Voice Dictation (Speech to text)" }),
    "aria-label": t("core.dictate.title", { default: "Voice Dictation (Speech to text)" }),
  }, icon("mic"), h("span", { class: "dictate-label" }, t("core.dictate.btn", { default: "Dictate" })));

  function stop() {
    listening = false;
    btn.classList.remove("is-listening");
    try { recognition?.stop(); } catch { /* ignore */ }
    recognition = null;
  }

  function start() {
    try {
      recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = false;

      const isAr = document.documentElement.lang === "ar" || document.documentElement.dir === "rtl";
      recognition.lang = isAr ? "ar-SA" : "en-US";

      recognition.onstart = () => {
        listening = true;
        btn.classList.add("is-listening");
      };

      recognition.onresult = (event) => {
        let finalTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          }
        }
        if (finalTranscript.trim()) {
          const text = finalTranscript.trim();
          const start = textarea.selectionStart ?? textarea.value.length;
          const end = textarea.selectionEnd ?? textarea.value.length;
          const cur = textarea.value;
          const before = cur.slice(0, start);
          const after = cur.slice(end);
          const spacer = (before.length && !before.endsWith(" ") && !before.endsWith("\n")) ? " " : "";
          textarea.value = before + spacer + text + after;
          const nextPos = (before + spacer + text).length;
          textarea.selectionStart = textarea.selectionEnd = nextPos;
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          textarea.focus();
        }
      };

      recognition.onerror = (e) => {
        stop();
        if (e.error !== "no-speech") {
          toast(t("core.dictate.error", { default: "Microphone access error: {error}", error: e.error }), { type: "warning" });
        }
      };

      recognition.onend = () => {
        stop();
      };

      recognition.start();
    } catch (err) {
      stop();
      toast(err.message, { type: "error" });
    }
  }

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (listening) {
      stop();
    } else {
      start();
    }
  });

  return btn;
}
