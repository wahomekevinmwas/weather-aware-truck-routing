import { useEffect, useRef, useState } from "react";
import { answerQuestion, PRESETS } from "./explain.js";

// Explainer: a floating "?" button (bottom-right) that opens a small panel.
// It is NOT an AI model. Each answer is built in the browser from the plan data in `result`
// (see explain.js), so it never invents weather and never changes the recommendation.
// Props come from App: `result` (the plan, or null) and `selectedIndex` (the route chosen on the map).
export default function Explainer({ result, selectedIndex }) {
  const [open, setOpen] = useState(false); // is the panel showing?
  const [messages, setMessages] = useState([]); // each one: { from: "you" or "bot", text: "..." }
  const [draft, setDraft] = useState(""); // what is typed in the box
  const listRef = useRef(null); // lets us scroll the message list to the bottom

  // A new plan makes the old answers stale, so clear the conversation whenever `result` changes.
  useEffect(() => {
    setMessages([]);
  }, [result]);

  // Keep the newest message in view.
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, open]);

  function ask(question) {
    const q = question.trim();
    if (!q) return;
    const reply = answerQuestion(q, result, selectedIndex);
    setMessages((old) => [...old, { from: "you", text: q }, { from: "bot", text: reply }]);
    setDraft("");
  }

  return (
    <div className="explainer">
      {open && (
        <section className="panel ex-panel" aria-label="Route explainer">
          <div className="ex-head">
            <strong>Route explainer</strong>
            <button type="button" className="icon-btn" aria-label="Close explainer" onClick={() => setOpen(false)}>
              x
            </button>
          </div>
          <p className="muted ex-note">Answers come from the plan on screen. It never changes the recommendation.</p>
          <div className="ex-list" ref={listRef}>
            {messages.length === 0 && (
              <p className="muted">{result ? "Pick a question or type your own." : "Plan a trip first, then ask about the routes."}</p>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`ex-msg ${m.from}`}>
                {m.text.split("\n").map((line, j) => (
                  <p key={j}>{line}</p>
                ))}
              </div>
            ))}
          </div>
          <div className="ex-presets">
            {PRESETS.map((p) => (
              <button key={p} type="button" disabled={!result} onClick={() => ask(p)}>
                {p}
              </button>
            ))}
          </div>
          <form
            className="ex-form"
            onSubmit={(e) => {
              e.preventDefault();
              ask(draft);
            }}
          >
            <input
              value={draft}
              maxLength={200}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about this plan..."
              disabled={!result}
            />
            <button type="submit" className="primary" disabled={!result}>
              Ask
            </button>
          </form>
        </section>
      )}
      <button type="button" className="ex-fab" aria-label="Open route explainer" title="Route explainer" onClick={() => setOpen(!open)}>
        ?
      </button>
    </div>
  );
}
