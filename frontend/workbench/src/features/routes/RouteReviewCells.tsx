import { useState } from 'react';
import type { RouteItem } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { InlineEditTrigger, PopoverFooter } from '@/components/ui/workbench-shell';
import { ROUTE_STATUS_LABELS as statusLabels } from '@/domain/palette';
import { STATUS_ORDER } from './RouteFilterBar';

export function routeStatusBadgeVariant(status: string) {
  if (status === 'verified' || status === 'manual') return 'success' as const;
  if (status === 'rejected') return 'destructive' as const;
  return 'secondary' as const;
}

interface RouteReviewCellProps {
  item: RouteItem;
  canEdit: boolean;
  saving: boolean;
  onSave(routeId: string, status: string, note: string | null): Promise<boolean>;
}

export function RouteStatusCell({ item, canEdit, saving, onSave }: RouteReviewCellProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(item.status);

  if (!canEdit) {
    return (
      <Badge variant={routeStatusBadgeVariant(item.status)}>
        {statusLabels[item.status] ?? item.status}
      </Badge>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={next => {
        if (next) setDraft(item.status);
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <InlineEditTrigger aria-label={`编辑路径 ${item.route_id} 状态`}>
          <Badge variant={routeStatusBadgeVariant(item.status)}>
            {statusLabels[item.status] ?? item.status}
          </Badge>
        </InlineEditTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-48 space-y-2.5 p-3">
        <div className="text-xs font-semibold text-foreground">修改状态</div>
        <RadioGroup value={draft} onValueChange={setDraft} className="gap-1">
          {STATUS_ORDER.map(status => (
            <Label
              key={status}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 font-normal hover:bg-accent"
            >
              <RadioGroupItem value={status} />
              <span>{statusLabels[status]}</span>
            </Label>
          ))}
        </RadioGroup>
        <PopoverFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            disabled={saving}
            onClick={async () => {
              if (await onSave(item.route_id, draft, item.note)) setOpen(false);
            }}
          >
            保存
          </Button>
        </PopoverFooter>
      </PopoverContent>
    </Popover>
  );
}

export function RouteNoteCell({ item, canEdit, saving, onSave }: RouteReviewCellProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(item.note ?? '');

  if (!canEdit) {
    return (
      <span className="block truncate text-muted-foreground" title={item.note ?? ''}>
        {item.note || '—'}
      </span>
    );
  }

  const commit = async () => {
    if (await onSave(item.route_id, item.status, draft)) setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={next => {
        if (next) setDraft(item.note ?? '');
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <InlineEditTrigger
          className="max-w-full justify-start text-muted-foreground hover:text-foreground"
          aria-label={`编辑路径 ${item.route_id} 备注`}
        >
          <span className="truncate">{item.note || '—'}</span>
        </InlineEditTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-2.5 p-3">
        <div className="text-xs font-semibold text-foreground">编辑备注</div>
        <Input
          placeholder="填写备注（留空清空）"
          value={draft}
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') void commit();
          }}
        />
        <PopoverFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button variant="default" size="sm" disabled={saving} onClick={() => void commit()}>
            保存
          </Button>
        </PopoverFooter>
      </PopoverContent>
    </Popover>
  );
}
