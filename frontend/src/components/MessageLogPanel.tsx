import React, { useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useSimulationStore } from '@/simulation/store';

// Message types for color coding
const MESSAGE_COLORS: Record<string, string> = {
  MQTT: '#3B82F6',     // Blue - server to truck
  MQTT_SENT: '#22C55E', // Green - truck to server  
  P2P: '#F97316',      // Orange - truck to truck
  ALERT: '#EF4444',    // Red - alerts/S7
  INFO: '#64748B',     // Gray - info
};

// Single message entry
interface LogEntry {
  id: string;
  time: string;
  type: string;
  message: string;
  color: string;
}

export const MessageLogPanel: React.FC = () => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<LogEntry[]>([]);
  const maxMessages = 50;
  
  // Subscribe to store log messages
  useEffect(() => {
    // Listen for MQTT messages
    const handleMqttMessage = (event: CustomEvent) => {
      const { topic, payload } = event.detail || {};
      addMessage('MQTT', topic, payload);
    };
    
    window.addEventListener('mqtt:message', handleMqttMessage as EventListener);
    
    return () => {
      window.removeEventListener('mqtt:message', handleMqttMessage as EventListener);
    };
  }, []);
  
  // Also read from simulation store if it has log
  const storeMessages = useSimulationStore(state => (state as any).log || []);
  
  useEffect(() => {
    // Convert store messages to log entries
    if (storeMessages?.length > 0) {
      const newEntries: LogEntry[] = storeMessages.slice(-maxMessages).map((m: any, i: number) => ({
        id: `${Date.now()}-${i}`,
        time: new Date().toLocaleTimeString(),
        type: m.type || 'INFO',
        message: m.msg || JSON.stringify(m),
        color: MESSAGE_COLORS[m.type] || MESSAGE_COLORS.INFO,
      }));
      setMessages(newEntries);
    }
  }, [storeMessages]);
  
  const addMessage = (type: string, topic: string, payload: any) => {
    const color = MESSAGE_COLORS[type] || MESSAGE_COLORS.INFO;
    const message = typeof payload === 'object' ? JSON.stringify(payload).slice(0, 100) : String(payload);
    
    const entry: LogEntry = {
      id: `${Date.now()}-${Math.random()}`,
      time: new Date().toLocaleTimeString(),
      type,
      message: `[${topic}] ${message}`,
      color,
    };
    
    setMessages(prev => {
      const updated = [...prev, entry];
      return updated.slice(-maxMessages);
    });
    
    // Auto-scroll to bottom
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  };
  
  const clearMessages = () => {
    setMessages([]);
  };
  
  return (
    <Card className="bg-slate-900 border-slate-700">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-slate-200 flex items-center justify-between">
          <span>LIVE MESSAGE LOG</span>
          <Button 
            variant="ghost" 
            size="sm"
            onClick={clearMessages}
            className="h-6 text-xs text-slate-400"
          >
            Clear
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[200px] px-4">
          <div className="space-y-1 py-2">
            {messages.length === 0 ? (
              <div className="text-xs text-slate-500 text-center py-4">
                Waiting for messages...
              </div>
            ) : (
              messages.map(msg => (
                <div 
                  key={msg.id} 
                  className="text-xs font-mono py-0.5"
                  style={{ color: msg.color }}
                >
                  <span className="text-slate-500">[{msg.time}]</span>
                  {' '}
                  <span className="font-semibold">[{msg.type}]</span>
                  {' '}
                  <span className="text-slate-300">{msg.message}</span>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
};

// Legend for message types
export const MessageLogLegend: React.FC = () => (
  <div className="flex flex-wrap gap-2 text-xs">
    <span className="flex items-center gap-1">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: MESSAGE_COLORS.MQTT }} />
      Server→Truck
    </span>
    <span className="flex items-center gap-1">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: MESSAGE_COLORS.MQTT_SENT }} />
      Truck→Server
    </span>
    <span className="flex items-center gap-1">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: MESSAGE_COLORS.P2P }} />
      P2P
    </span>
    <span className="flex items-center gap-1">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: MESSAGE_COLORS.ALERT }} />
      Alert
    </span>
  </div>
);

export default MessageLogPanel;