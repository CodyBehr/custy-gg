import type { Metadata } from "next";

export const metadata: Metadata = { title: "Sign in" };

type Props = { searchParams: Promise<{ next?: string; wrong?: string }> };

export default async function Login({ searchParams }: Props) {
  const { next = "/", wrong } = await searchParams;
  return (
    <div className="login">
      <h1>Members only</h1>
      <p className="muted">Enter the group password to see the stats. You&apos;ll stay signed in on this device.</p>
      <form method="post" action="/api/login">
        <input type="hidden" name="next" value={next} />
        <input type="password" name="password" placeholder="Group password" aria-label="Group password" autoFocus required />
        {wrong ? <p className="err">That password isn&apos;t right. Ask whoever set up the site.</p> : null}
        <button className="btn" type="submit">Sign in</button>
      </form>
    </div>
  );
}
