import Link from "next/link";

export default function Nav() {
  return (
    <nav className="flex gap-4 text-sm">
      <Link href="/" className="hover:underline">Scenario</Link>
      <Link href="/plan" className="hover:underline">Plan</Link>
      <Link href="/proposals" className="hover:underline">Proposals</Link>
    </nav>
  );
}
