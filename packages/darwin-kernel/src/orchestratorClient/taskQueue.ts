/**
 * Task queue client — thin interface every product uses to enqueue cross-project
 * work onto the orchestrator's control plane and to read approval state. Mirrors
 * the orchestrator's Supabase `tasks` + approval-card model so the bot fleets in
 * tomorrow/smarter/apparently stop reinventing their own loops (opportunity #2).
 */
import type { ProductId, Decision } from '../types.ts';

export type TaskState = 'queued' | 'running' | 'done' | 'blocked' | 'testfail' | 'merged';

export interface QueuedTask {
  id: string;
  product: ProductId;
  /** capability id or freeform goal */
  goal: string;
  input: Record<string, unknown>;
  state: TaskState;
  /** ids this task depends on (DAG) */
  dependsOn: string[];
  /** if material, the task waits on an approval card */
  requiresApproval: boolean;
  createdAt: string;
}

export interface ApprovalCard {
  taskId: string;
  why: string;
  value: string;
  risk: string;
  alternatives: string[];
  decision: Decision | 'pending';
}

export interface TaskQueueTransport {
  enqueue(task: QueuedTask): Promise<void>;
  get(id: string): Promise<QueuedTask | null>;
  setState(id: string, state: TaskState): Promise<void>;
  upsertApproval(card: ApprovalCard): Promise<void>;
  pendingApprovals(product?: ProductId): Promise<ApprovalCard[]>;
}

export class TaskQueueClient {
  private readonly transport: TaskQueueTransport;
  constructor(transport: TaskQueueTransport) {
    this.transport = transport;
  }

  enqueue(task: QueuedTask): Promise<void> {
    return this.transport.enqueue(task);
  }
  get(id: string): Promise<QueuedTask | null> {
    return this.transport.get(id);
  }
  advance(id: string, state: TaskState): Promise<void> {
    return this.transport.setState(id, state);
  }
  requestApproval(card: ApprovalCard): Promise<void> {
    return this.transport.upsertApproval(card);
  }
  inbox(product?: ProductId): Promise<ApprovalCard[]> {
    return this.transport.pendingApprovals(product);
  }
}
