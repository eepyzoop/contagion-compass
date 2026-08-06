"use client";

import { useState } from "react";
import styles from "./page.module.css";

export default function QueryBox() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);

  async function ask(e) {
    e.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
    setAnswer(null);
    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      setAnswer(res.ok ? data.answer : `Error: ${data.error}`);
    } catch {
      setAnswer("Error: request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={ask} className={styles.card}>
      <input
        type="text"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Ask about past runs, e.g. how does this compare to last season?"
        className={styles.queryInput}
      />
      <button type="submit" disabled={loading} className={styles.queryButton}>
        {loading ? "Asking..." : "Ask"}
      </button>
      {answer && <p>{answer}</p>}
    </form>
  );
}
