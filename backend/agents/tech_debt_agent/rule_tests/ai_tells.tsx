import { useEffect, useState } from "react";

declare const url: string;

export function A() {
  const [d, setD] = useState(null);
  useEffect(() => {
    // ruleid: use-effect-fetch-sin-dependencias
    fetch("/a").then((r) => r.json());
  });
  useEffect(() => {
    async function load() {
      // ruleid: use-effect-fetch-sin-dependencias
      const r = await fetch(url);
      // ruleid: use-effect-estado-sin-dependencias
      setD(await r.json());
    }
    load();
  });
  useEffect(() => {
    // ok: use-effect-fetch-sin-dependencias
    fetch("/a");
    // ok: use-effect-estado-sin-dependencias
    setD(1);
  }, []);
  // ok: use-effect-fetch-sin-dependencias
  fetch("/b");
  return null;
}

// ruleid: parseo-manual-de-url
const base = url.split("?")[0];
// ruleid: parseo-manual-de-url
const rest = url.split("://")[1];
// ok: parseo-manual-de-url
const parts = url.split(",");
