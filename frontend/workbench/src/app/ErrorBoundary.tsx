import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';

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
        <Card className="w-full max-w-md shadow-md">
          <CardHeader className="p-6 pb-4">
            <CardTitle className="text-base">工作台渲染异常</CardTitle>
            <CardDescription className="break-words text-[13px]">
              {this.state.error.message || '发生了未预期的界面错误'}
            </CardDescription>
          </CardHeader>
          <CardFooter className="p-6 pt-0">
            <Button variant="outline" onClick={() => this.setState({ error: null })}>
              尝试恢复
            </Button>
            <Button variant="default" onClick={() => window.location.reload()}>
              重新加载页面
            </Button>
          </CardFooter>
        </Card>
      </main>
    );
  }
}
