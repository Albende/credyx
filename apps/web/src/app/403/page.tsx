import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-bg-base text-center px-8">
      <h1 className="text-display-lg">403</h1>
      <p className="text-fg-muted mt-4">You don&apos;t have access to this page.</p>
      <Link href="/" className="mt-6 text-brand-primary underline">Back to home</Link>
    </main>
  );
}
