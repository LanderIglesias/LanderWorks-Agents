import { useEffect, useState } from "react";

export default function App() {
  const [html, setHtml] = useState("");

  useEffect(() => {
    fetch("/api/content")
      .then((r) => r.text())
      .then(setHtml);
  });

  const parse = (raw: string) => {
    try {
      return JSON.parse(raw);
    } catch {}
  };

  console.log("render", parse(html));

  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
