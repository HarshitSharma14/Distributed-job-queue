import { LoaderCircle, TriangleAlert } from "lucide-react";

export function FullPageLoader() {
  return (
    <div className="grid min-h-screen place-items-center bg-[#f6f7f2]">
      <LoaderCircle className="h-7 w-7 animate-spin text-indigo-600" aria-label="Loading" />
    </div>
  );
}

export function PageError({ message = "This view could not be loaded." }: { message?: string }) {
  return (
    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-900">
      <TriangleAlert className="mb-3 h-6 w-6" />
      <p className="font-semibold">Something interrupted the signal</p>
      <p className="mt-1 text-sm text-rose-700">{message}</p>
    </div>
  );
}
