// MQTT Communication Service
// Handles MQTT messaging for truck-to-server communication
// Every truck movement should be triggered by MQTT messages, not JS timers

import mqtt from 'mqtt';

const MQTT_BROKER = import.meta.env.VITE_MQTT_BROKER || 'ws://127.0.0.1:9001';
const MQTT_TOPICS = {
  TRUCK_STATE: 'mines/+/trucks/+/state',
  TRUCK_ASSIGNMENT: 'mines/+/trucks/+/assignment',
  DSDE_STRATEGY: 'mines/+/dsde/strategy',
  ALERTS: 'mines/+/alerts',
  SURFACE_UPDATE: 'mines/+/dump/+/surface/update',
};

type EventCallback = (...args: any[]) => void;

type MessageHandler = (topic: string, payload: object) => void;

class MQTTService {
  private client: mqtt.MqttClient | null = null;
  private connected: boolean = false;
  private messageHandlers: Map<string, MessageHandler[]> = new Map();
  private pendingMessages: Map<string, object[]> = new Map();
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;

  constructor() {
    this.connect();
  }

  private connect() {
    try {
      this.client = mqtt.connect(MQTT_BROKER, {
        clientId: `adps_frontend_${Date.now()}`,
       CleanSession: true,
        reconnectPeriod: 5000,
        connectTimeout: 30000,
      });

      this.client.on('connect', () => {
        console.log('[MQTT] Connected to broker');
        this.connected = true;
        this.reconnectAttempts = 0;
        this.subscribeToTopics();
        // Emit custom event
        window.dispatchEvent(new CustomEvent('mqtt:connected'));
      });

      this.client.on('message', (topic, message) => {
        try {
          const payload = JSON.parse(message.toString());
          this.handleMessage(topic, payload);
        } catch (e) {
          console.error('[MQTT] Failed to parse message:', e);
        }
      });

      this.client.on('error', (err) => {
        console.error('[MQTT] Error:', err);
        this.connected = false;
      });

      this.client.on('close', () => {
        console.log('[MQTT] Disconnected');
        this.connected = false;
        window.dispatchEvent(new CustomEvent('mqtt:disconnected'));
      });

      this.client.on('reconnect', () => {
        this.reconnectAttempts++;
        console.log(`[MQTT] Reconnecting... attempt ${this.reconnectAttempts}`);
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
          console.error('[MQTT] Max reconnect attempts reached');
          this.client?.end();
        }
      });
    } catch (e) {
      console.error('[MQTT] Failed to connect:', e);
    }
  }

  private subscribeToTopics() {
    if (!this.client || !this.connected) return;
    
    Object.values(MQTT_TOPICS).forEach(topic => {
      this.client?.subscribe(topic, { qos: 1 }, (err) => {
        if (err) {
          console.error(`[MQTT] Failed to subscribe to ${topic}:`, err);
        }
      });
    });
  }

  private handleMessage(topic: string, payload: object) {
    const handlers = this.messageHandlers.get(topic);
    if (handlers) {
      handlers.forEach(handler => handler(topic, payload));
    }

    // Also try wildcard matching
    this.messageHandlers.forEach((handlers, pattern) => {
      if (this.topicMatches(topic, pattern)) {
        handlers.forEach(handler => handler(topic, payload));
      }
    });

    // Emit event for general listeners
    window.dispatchEvent(new CustomEvent('mqtt:message', { detail: { topic, payload } }));
  }

  private topicMatches(topic: string, pattern: string): boolean {
    if (pattern.includes('+') || pattern.includes('#')) {
      const regex = new RegExp(
        '^' + pattern
          .replace(/\+/g, '[^/]+')
          .replace(/#/g, '.*') + '$'
      );
      return regex.test(topic);
    }
    return false;
  }

  subscribe(topic: string, handler: MessageHandler) {
    if (!this.messageHandlers.has(topic)) {
      this.messageHandlers.set(topic, []);
    }
    this.messageHandlers.get(topic)?.push(handler);
  }

  unsubscribe(topic: string, handler: MessageHandler) {
    const handlers = this.messageHandlers.get(topic);
    if (handlers) {
      const index = handlers.indexOf(handler);
      if (index > -1) {
        handlers.splice(index, 1);
      }
    }
  }

  publish(topic: string, payload: object) {
    if (!this.client || !this.connected) {
      // Queue message for later
      const pending = this.pendingMessages.get(topic) || [];
      pending.push(payload);
      this.pendingMessages.set(topic, pending);
      console.warn('[MQTT] Not connected, queuing message:', topic);
      return;
    }

    this.client.publish(topic, JSON.stringify(payload), { qos: 1 }, (err) => {
      if (err) {
        console.error('[MQTT] Publish error:', err);
      }
    });
  }

  // Send truck state update
  sendTruckState(truckId: string, state: object, mineId: string = 'default') {
    const topic = `mines/${mineId}/trucks/${truckId}/state`;
    this.publish(topic, {
      msg_type: 'TRUCK_STATE',
      protocol_version: '1.0',
      truck_id: truckId,
      timestamp_utc: new Date().toISOString(),
      ...state,
    });
  }

  // Send dump complete notification
  sendDumpComplete(truckId: string, zoneId: string, dumpData: object, mineId: string = 'default') {
    const topic = `mines/${mineId}/dump/${zoneId}/surface/update`;
    this.publish(topic, {
      msg_type: 'SURFACE_UPDATE',
      protocol_version: '1.0',
      event: 'DUMP_COMPLETE',
      truck_id: truckId,
      timestamp_utc: new Date().toISOString(),
      ...dumpData,
    });
  }

  isConnected(): boolean {
    return this.connected;
  }

  disconnect() {
    this.client?.end();
    this.connected = false;
  }
}

// Singleton instance
export const mqttService = new MQTTService();

// Event emitter for general MQTT events
export const MQTT_EVENTS = {
  CONNECTED: 'mqtt:connected',
  DISCONNECTED: 'mqtt:disconnected',
  MESSAGE: 'mqtt:message',
} as const;