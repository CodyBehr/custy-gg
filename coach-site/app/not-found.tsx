import SearchBox from "@/components/SearchBox";

export default function NotFound() {
  return (
    <div className="error-box">
      <h1>Page not found</h1>
      <p className="muted">Search for a player instead.</p>
      <SearchBox big />
    </div>
  );
}
