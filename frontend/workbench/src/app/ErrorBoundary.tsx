import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

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
    console.error('Workbench render error:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="loading-screen error-boundary" role="alert">
        <div className="panel error-boundary-card">
          <h2>工作台渲染异常</h2>
          <p>{this.state.error.message || '发生了未预期的界面错误'}</p>
          <div className="error-boundary-actions">
            <button className="secondary-button" onClick={() => this.setState({ error: null })}>
              尝试恢复
            </button>
            <button className="primary-button" onClick={() => window.location.reload()}>
              重新加载页面
            </button>
          </div>
        </div>
      </main>
    );
  }
}
