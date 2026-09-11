import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, TriangleAlert, X } from "lucide-react";

type Confirmation = {
  title: string;
  description: string;
  label?: string;
  destructive?: boolean;
};
type Notice = { id: number; message: string; error: boolean };
const Context = createContext<{
  notify: (message: string, error?: boolean) => void;
  confirm: (options: Confirmation) => Promise<boolean>;
} | null>(null);

export function InteractionProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const counter = useRef(0);
  const notify = useCallback((message: string, error = false) => {
    setNotices((items) => [
      ...items.slice(-2),
      { id: ++counter.current, message, error },
    ]);
  }, []);
  const confirm = useCallback(
    (options: Confirmation) =>
      new Promise<boolean>((resolve) => {
        resolver.current?.(false);
        resolver.current = resolve;
        setConfirmation(options);
      }),
    [],
  );
  function close(value: boolean) {
    dialog.current?.close();
    resolver.current?.(value);
    resolver.current = null;
    setConfirmation(null);
  }
  useEffect(() => {
    if (confirmation) dialog.current?.showModal();
  }, [confirmation]);
  useEffect(() => () => resolver.current?.(false), []);
  return (
    <Context.Provider value={{ notify, confirm }}>
      {children}
      <div className="toast-stack" aria-label="Notifications">
        {notices.map((notice) => (
          <NoticeItem
            key={notice.id}
            notice={notice}
            dismiss={() =>
              setNotices((items) =>
                items.filter((item) => item.id !== notice.id),
              )
            }
          />
        ))}
      </div>
      <dialog
        ref={dialog}
        className="confirmation"
        aria-labelledby="confirmation-title"
        aria-describedby="confirmation-description"
        onCancel={(event) => {
          event.preventDefault();
          close(false);
        }}
      >
        {confirmation && (
          <>
            <h2 id="confirmation-title">{confirmation.title}</h2>
            <p id="confirmation-description">{confirmation.description}</p>
            <div className="dialog-actions">
              <button
                className="button button-secondary"
                autoFocus
                onClick={() => close(false)}
              >
                Cancel
              </button>
              <button
                className={`button button-${confirmation.destructive === false ? "primary" : "danger"}`}
                onClick={() => close(true)}
              >
                {confirmation.label ?? "Confirm"}
              </button>
            </div>
          </>
        )}
      </dialog>
    </Context.Provider>
  );
}
function NoticeItem({
  notice,
  dismiss,
}: {
  notice: Notice;
  dismiss: () => void;
}) {
  const dismissRef = useRef(dismiss);
  useEffect(() => {
    dismissRef.current = dismiss;
  });
  useEffect(() => {
    if (!notice.error) {
      const timer = setTimeout(() => dismissRef.current(), 7000);
      return () => clearTimeout(timer);
    }
  }, [notice.error]);
  const Icon = notice.error ? TriangleAlert : CheckCircle2;
  return (
    <div
      className={`toast ${notice.error ? "toast-error" : ""}`}
      role={notice.error ? "alert" : "status"}
    >
      <Icon size={17} aria-hidden="true" />
      <p>{notice.message}</p>
      <button
        className="icon-button"
        aria-label="Dismiss notification"
        onClick={dismiss}
      >
        <X size={16} />
      </button>
    </div>
  );
}
export function useInteraction() {
  const context = useContext(Context);
  if (!context) throw new Error("InteractionProvider is required");
  return context;
}
