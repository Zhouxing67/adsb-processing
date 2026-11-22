import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Button } from '@/components/ui/button';

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
      <main className="grid min-h-full place-items-center bg-[var(--canvas)] p-6" role="alert">
        <div className="w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-md">
          <h2 className="mb-2 text-base font-semibold text-foreground">工作台渲染异常</h2>
          <p className="mb-4 break-words text-[13px] text-muted-foreground">
            {this.state.error.message || '发生了未预期的界面错误'}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => this.setState({ error: null })}>
              尝试恢复
            </Button>
            <Button variant="default" onClick={() => window.location.reload()}>
              重新加载页面
            </Button>
          </div>
        </div>
      </main>
    );
  }
}
