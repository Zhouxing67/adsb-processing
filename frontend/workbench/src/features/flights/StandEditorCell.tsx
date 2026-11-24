import { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import type { FlightItem } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { InlineEditTrigger, PopoverFooter } from '@/components/ui/workbench-shell';

interface StandEditorCellProps {
  item: FlightItem;
  standOptions: string[];
  onSave(flightKey: string, standValue: string | null): Promise<void>;
}

export function StandEditorCell({ item, standOptions, onSave }: StandEditorCellProps) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(item.stand_position ?? '');
  const [search, setSearch] = useState('');
  const [showRecommendations, setShowRecommendations] = useState(false);
  const [recommendations, setRecommendations] = useState<Awaited<ReturnType<typeof api.recommendStands>> | null>(null);
  const [recommendationError, setRecommendationError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !showRecommendations) return;
    const controller = new AbortController();
    setRecommendations(null);
    setRecommendationError('');
    api
      .recommendStands(item.flight_key, controller.signal)
      .then(result => {
        if (!controller.signal.aborted) setRecommendations(result);
      })
      .catch(failure => {
        if (!controller.signal.aborted) {
          setRecommendationError(failure instanceof Error ? failure.message : '推荐读取失败');
        }
      });
    return () => controller.abort();
  }, [item.flight_key, open, showRecommendations]);

  const editableStands = useMemo(() => {
    const query = search.trim().toLowerCase();
    const candidates = ['', ...standOptions];
    if (!query) return candidates;
    return candidates.filter(stand => (stand || '空机位').toLowerCase().includes(query));
  }, [search, standOptions]);

  if (!item.can_edit_stand) {
    return <span className="text-muted-foreground">{item.stand_position || '—'}</span>;
  }

  const standColumn = item.movement_type === 'departure' ? 'dep_stand_position' : 'arr_stand_position';
  const canRecommend = !item.stand_position && !item.inconsistent_fields.includes(standColumn);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(item.flight_key, value.trim() || null);
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={nextOpen => {
        setOpen(nextOpen);
        if (nextOpen) {
          setShowRecommendations(false);
          setValue(item.stand_position ?? '');
          setSearch('');
        }
      }}
    >
      <PopoverTrigger asChild>
        <InlineEditTrigger className="stand-edit-trigger" title="点击编辑机位">
          {item.stand_position || '选择机位'}
        </InlineEditTrigger>
      </PopoverTrigger>
      <PopoverContent
        role="dialog"
        aria-label={`编辑 ${item.flight_id} 机位`}
        className="w-64 space-y-2.5 p-3"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-foreground">编辑机位</span>
          {canRecommend && (
            <Button variant="outline" size="xs" onClick={() => setShowRecommendations(prev => !prev)}>
              {showRecommendations ? '返回机位搜索' : '推荐机位'}
            </Button>
          )}
        </div>
        {!showRecommendations && (
          <Input
            type="search"
            aria-label="搜索可选机位"
            placeholder="搜索机位"
            value={search}
            onChange={event => setSearch(event.target.value)}
          />
        )}
        <ScrollArea className="h-44">
          <RadioGroup
            value={value ? value : '__empty__'}
            onValueChange={next => setValue(next === '__empty__' ? '' : next)}
            className="gap-0.5 pr-2"
          >
            {showRecommendations && !recommendations && (
              <small role="status" className="px-2 text-muted-foreground">
                {recommendationError || '正在查找推荐机位…'}
              </small>
            )}
            {showRecommendations && recommendations && (
              recommendations.high.length + recommendations.medium.length === 0 ? (
                <small role="status" className="px-2 text-muted-foreground">
                  暂无推荐机位
                </small>
              ) : (
                (['high', 'medium'] as const).map(
                  group =>
                    recommendations[group].length > 0 && (
                      <div key={group} className="space-y-1 py-1">
                        <Badge variant="secondary">{group === 'high' ? '高置信度' : '中置信度'}</Badge>
                        {recommendations[group].map(candidate => (
                          <Label
                            key={candidate.stand}
                            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 font-normal hover:bg-accent"
                          >
                            <RadioGroupItem value={candidate.stand} aria-label={candidate.stand} />
                            <span>
                              {candidate.stand}
                              <small className="block text-muted-foreground">
                                {'nearest_m' in candidate
                                  ? `停靠端 ${candidate.consecutive_points} 个点，最近 ${candidate.nearest_m.toFixed(1)} 米`
                                  : `近 90 天使用 ${candidate.uses}/${candidate.total} 次，未发现同期占用`}
                              </small>
                            </span>
                          </Label>
                        ))}
                      </div>
                    ),
                )
              )
            )}
            {!showRecommendations &&
              editableStands.map(stand => {
                const label = stand || '空机位';
                return (
                  <Label
                    key={stand || '__empty'}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 font-normal text-foreground hover:bg-accent"
                  >
                    <RadioGroupItem value={stand || '__empty__'} aria-label={label} />
                    <span>{label}</span>
                  </Label>
                );
              })}
          </RadioGroup>
        </ScrollArea>
        <PopoverFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button variant="default" size="sm" disabled={saving} onClick={() => void handleSave()}>
            保存
          </Button>
        </PopoverFooter>
      </PopoverContent>
    </Popover>
  );
}
