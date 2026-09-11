/**
 * Last line of defence against a blank page.
 *
 * When a React render throws, the default behaviour is to unmount the whole
 * tree — the page goes white with nothing in the accessibility tree at all. A
 * sighted user at least sees that something broke; a screen-reader user gets
 * silence and no way to tell a crash from a slow request.
 *
 * So any render error becomes a real heading, a real alert, and a way out.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("EchoNotes crashed while rendering:", error, info);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <main id="main" className="panel">
        <h1>Something went wrong</h1>
        <p role="alert" className="error">
          {error.message || "The page failed to render."}
        </p>
        <p className="muted">
          This is usually the backend returning something unexpected. Check that
          it is running, then reload.
        </p>
        <button
          type="button"
          className="primary"
          onClick={() => window.location.reload()}
        >
          Reload the page
        </button>
      </main>
    );
  }
}
