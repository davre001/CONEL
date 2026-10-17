import Link from "next/link";
export default function Success() {
  return (
    <main>
      <nav>CONEL / OBJECTS</nav>
      <h1>Checkout returned.</h1>
      <p>
        This page does not confirm payment. Verify the Stripe test session in
        your dashboard.
      </p>
      <Link href="/">Back to the store ?</Link>
    </main>
  );
}
