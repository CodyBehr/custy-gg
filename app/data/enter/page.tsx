import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { dashToken } from "@/lib/dash";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

export default async function Enter({ searchParams }: { searchParams: Promise<{ wrong?: string }> }) {
  if (!(await dashToken())) notFound();
  const { wrong } = await searchParams;
  return (
    <div className="login">
      <h1>Data</h1>
      <form method="post" action="/api/data-login">
        <input type="password" name="password" placeholder="Password" aria-label="Password" autoFocus required />
        {wrong ? <p className="err">Not right.</p> : null}
        <button className="btn" type="submit">Open</button>
      </form>
    </div>
  );
}
