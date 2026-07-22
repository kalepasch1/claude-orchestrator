export type ConfigRequestStatus = 'pending' | 'approved' | 'rejected';
export type ConfigApprovalDecision = 'approved' | 'rejected';

export interface ConfigRequest {
  id: string;
  key: string;
  value: string;
  requester: string;
  status: ConfigRequestStatus;
  created_at: string;
}

export interface ConfigApproval {
  id: string;
  request_id: string;
  approver: string;
  decision: ConfigApprovalDecision;
  reason: string | null;
  decided_at: string;
}
