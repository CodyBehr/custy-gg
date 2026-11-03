import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel empty">
      <h2>Nothing here</h2>
      <p>That player or game isn&apos;t in the database. It may have been played before anyone ran the collector.</p>
      <p><Link href="/" className="win-t">Back to standings</Link></p>
    </div>
  );
}
