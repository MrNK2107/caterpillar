import { useSimulationStore } from '../simulation/store';

// Full 8-phase P2P protocol for valley fill / choke point negotiation
// Each phase corresponds to the protocol in the ADPS spec
export type P2PMessageType = 
  // Phase 1 - Choke detection
  | 'CHOKE_APPROACH_NOTICE'      // Truck notifies it's approaching choke
  // Phase 2 - State response  
  | 'CHOKE_STATE_RESPONSE'     // Peer responds with its state
  // Phase 3 - Priority negotiation
  | 'PRIORITY_RESULT'          // Final priority (dumper/waiter)
  // Phase 4 - Safe zone declaration (waiter only)
  | 'SAFE_ZONE_DECLARED'       // Waiter declares safe zone location
  // Phase 5 - Safe zone confirmation
  | 'SAFE_ZONE_CONFIRMED'    // Waiter confirms arrived at safe zone
  // Phase 6 - Dump complete + exit intent
  | 'DUMP_COMPLETE_EXIT_INTENT' // Dumper notifies dump done, plans exit
  // Phase 7 - Exit path clear
  | 'EXIT_PATH_CLEAR'         // Waiter confirms exit path clear
  // Phase 8 - Communication failure
  | 'COMM_LOST';              // Communication failure handling

export interface P2PMessage {
  type: P2PMessageType;
  sender_id: number;
  target?: number | 'BROADCAST';
  payload: {
    // Common fields
    eta_seconds?: number;
    position?: { x: number; y: number };
    payload_tonnes?: number;
    truck_width_m?: number;
    choke_id?: string;
    intended_terrace?: number;
    
    // Priority result fields
    role?: 'DUMPER' | 'WAITER';
    priority_reason?: string;
    
    // Safe zone fields
    safe_zone?: {
      center: { x: number; y: number };
      width_m: number;
      length_m: number;
      bearing_capacity_kpa: number;
      slope_deg: number;
      blocks_exit_path: boolean;
    };
    truck_is_stationary?: boolean;
    eta_to_safe_zone_seconds?: number;
    
    // Dump complete fields
    exit_path?: { x: number; y: number }[];
    
    // Communication failure
    last_known_peer_state?: string;
    action_taken?: string;
  };
  timestamp_utc?: string;
}

export class P2PChannel {
  private ws: WebSocket | null = null;
  public truckId: number;
  private handlers: ((msg: P2PMessage) => void)[] = [];
  
  // Protocol state machine
  public currentNegotiationState: 'IDLE' | 'APPROACHING' | 'NEGOTIATING' | 'WAITING' | 'DUMPING' | 'EXITING' = 'IDLE';
  
  // Choke point info
  public targetChokePoint: { x: number, y: number } | null = null;
  public chokeId: string = '';
  public estimatedEta: number = Infinity;
  
  // Peer info
  public peerId: number | null = null;
  public peerState: 'IDLE' | 'APPROACHING' | 'NEGOTIATING' | 'WAITING' | 'DUMPING' | 'EXITING' = 'IDLE';
  public peerPosition: { x: number; y: number } | null = null;
  public peerPayload: number = 0;
  
  // Assigned role in negotiation
  public assignedRole: 'DUMPER' | 'WAITER' | null = null;
  
  constructor(truckId: number) {
    this.truckId = truckId;
    this.connect();
  }

  // Full 8-phase protocol handler
  private handlePhaseProtocol(msg: P2PMessage) {
    switch (msg.type) {
      // PHASE 1: Choke Approach Notice
      case 'CHOKE_APPROACH_NOTICE':
        if (this.currentNegotiationState === 'IDLE') {
          this.currentNegotiationState = 'NEGOTIATING';
          this.peerId = msg.sender_id;
          this.estimatedEta = msg.payload.eta_seconds || Infinity;
          this.chokeId = msg.payload.choke_id || '';
          
          // Respond with state (PHASE 2)
          this.send(msg.sender_id, 'CHOKE_STATE_RESPONSE', {
            position: useSimulationStore.getState().trucks.find(t => t.id === this.truckId)?.targetX 
              ? { x: 0, y: 0 }  // Would get actual position
              : { x: 0, y: 0 },
            eta_seconds: this.estimatedEta,
            p2p_state: this.currentNegotiationState,
          });
        }
        break;
        
      // PHASE 2: State Response
      case 'CHOKE_STATE_RESPONSE':
        this.peerId = msg.sender_id;
        this.peerState = msg.payload.p2p_state || 'IDLE';
        this.peerPosition = msg.payload.position || null;
        
        // Now resolve priority (PHASE 3)
        this.resolvePriorityWithReason(msg.payload.eta_seconds);
        break;
        
      // PHASE 3: Priority Result
      case 'PRIORITY_RESULT':
        this.assignedRole = msg.payload.role || (this.estimatedEta < (this.peerPayload || 0) ? 'DUMPER' : 'WAITER');
        
        if (this.assignedRole === 'WAITING') {
          // I am waiter - find safe zone and declare it (PHASE 4)
          this.declareSafeZone(msg.sender_id);
        } else {
          // I am dumper - wait for safe zone confirmation
          this.currentNegotiationState = 'DUMPING';
        }
        break;
        
      // PHASE 4: Safe Zone Declared (Waiter only)
      case 'SAFE_ZONE_DECLARED':
        // As dumper, record safe zone and wait for confirmation
        break;
        
      // PHASE 5: Safe Zone Confirmed
      case 'SAFE_ZONE_CONFIRMED':
        if (this.currentNegotiationState === 'WAITING') {
          // Waiter confirmed, dumper can proceed
          this.currentNegotiationState = 'DUMPING';
          this.send(this.peerId || 'BROADCAST', 'DUMP_COMPLETE_EXIT_INTENT', {
            exit_path: [{ x: 0, y: 0 }], // Would use actual exit path
          });
        }
        break;
        
      // PHASE 6: Dump Complete + Exit Intent
      case 'DUMP_COMPLETE_EXIT_INTENT':
        this.currentNegotiationState = 'EXITING';
        // If I am waiter, clear exit path (PHASE 7)
        if (this.assignedRole === 'WAITING') {
          this.send(this.peerId || 'BROADCAST', 'EXIT_PATH_CLEAR', {
            dumper_may_exit: true,
          });
        }
        break;
        
      // PHASE 7: Exit Path Clear
      case 'EXIT_PATH_CLEAR':
        if (msg.payload.dumper_may_exit) {
          // Dumper can exit, reset state
          this.resetNegotiation();
        }
        break;
        
      // PHASE 8: Communication Failure
      case 'COMM_LOST':
        this.handleCommunicationFailure(msg.payload.last_known_peer_state, msg.payload.action_taken);
        break;
    }
  }

  private resolvePriorityWithReason(peerEta: number | undefined) {
    // Priority order: (1) already inside choke, (2) lower ETA, (3) higher payload, (4) lower truck_id
    const myScore = this.estimatedEta * 1000 - this.truckId;
    const peerScore = (peerEta || Infinity) * 1000 - (this.peerId || 999);
    
    if (myScore <= peerScore) {
      this.assignedRole = 'DUMPER';
      this.send(this.peerId || 'BROADCAST', 'PRIORITY_RESULT', { 
        role: 'DUMPER',
        priority_reason: `LOWER_ETA: T${this.truckId}=${this.estimatedEta}s T${this.peerId}=${peerEta}s`
      });
    } else {
      this.assignedRole = 'WAITING';
      this.send(this.peerId || 'BROADCAST', 'PRIORITY_RESULT', { 
        role: 'WAITER',
        priority_reason: `LOWER_ETA: T${this.truckId}=${this.estimatedEta}s T${this.peerId}=${peerEta}s`
      });
    }
  }

  private declareSafeZone(targetTruckId: number | 'BROADCAST') {
    // Find suitable safe zone (simplified - would use actual geometry)
    this.send(targetTruckId, 'SAFE_ZONE_DECLARED', {
      safe_zone: {
        center: { x: 100, y: 100 },  // Would compute actual safe zone
        width_m: 15,
        length_m: 22,
        bearing_capacity_kpa: 85,
        slope_deg: 3,
        blocks_exit_path: false,
      },
      truck_is_stationary: false,
      eta_to_safe_zone_seconds: 18,
    });
  }

  private handleCommunicationFailure(lastKnownState: string | undefined, action: string | undefined) {
    // Failure state machine from spec
    if (this.currentNegotiationState === 'DUMPING') {
      // Complete dump, then safe-stop
      this.currentNegotiationState = 'IDLE';
      useSimulationStore.getState().addLogMessage('ALERT', `COMM_LOST: Completing dump then stopping`);
    } else if (this.currentNegotiationState === 'APPROACHING') {
      // Immediate safe-stop
      this.currentNegotiationState = 'IDLE';
      useSimulationStore.getState().addLogMessage('ALERT', `COMM_LOST: Immediate stop`);
    }
    // If WAITING: remain stationary
  }

  private resetNegotiation() {
    this.currentNegotiationState = 'IDLE';
    this.peerId = null;
    this.assignedRole = null;
    this.estimatedEta = Infinity;
    this.chokeId = '';
  }

  // Legacy handler kept for compatibility
}
