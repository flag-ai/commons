package bonnie

import (
	"encoding/json"
	"time"
)

// GPUVendor identifies the GPU manufacturer on a BONNIE host.
type GPUVendor string

// Supported GPU vendor tags reported by BONNIE.
const (
	GPUVendorNVIDIA  GPUVendor = "nvidia"
	GPUVendorAMD     GPUVendor = "amd"
	GPUVendorIntel   GPUVendor = "intel"
	GPUVendorUnknown GPUVendor = "none"
)

// GPUInfo describes a single GPU on a BONNIE host. Field tags mirror
// BONNIE's gpu.Info struct — do not rename without coordinating.
type GPUInfo struct {
	Index       int       `json:"index"`
	Name        string    `json:"name"`
	Vendor      GPUVendor `json:"vendor"`
	MemoryTotal uint64    `json:"memory_total_mib"`
	MemoryFree  uint64    `json:"memory_free_mib"`
	Utilization int       `json:"utilization_percent"`
}

// GPUSnapshot is a point-in-time view of every GPU on a host.
type GPUSnapshot struct {
	Vendor    GPUVendor `json:"vendor"`
	GPUs      []GPUInfo `json:"gpus"`
	Timestamp time.Time `json:"timestamp"`
}

// GPUMetrics is the raw Prometheus text-exposition payload returned by
// BONNIE's /api/v1/gpu/metrics endpoint.
type GPUMetrics struct {
	ContentType string
	Body        string
}

// SystemInfo describes the host system reported by /api/v1/system/info.
type SystemInfo struct {
	Hostname string `json:"hostname"`
	OS       string `json:"os"`
	Arch     string `json:"arch"`
	Kernel   string `json:"kernel"`
	CPUModel string `json:"cpu_model"`
	CPUCores int    `json:"cpu_cores"`
	MemoryMB uint64 `json:"memory_mb"`
}

// DiskUsage reports disk usage as percentages and raw sizes.
type DiskUsage struct {
	TotalGB     float64 `json:"total_gb"`
	UsedGB      float64 `json:"used_gb"`
	AvailableGB float64 `json:"available_gb"`
	UsedPercent string  `json:"used_percent"`
}

// SystemInfoResponse combines system info and disk usage.
type SystemInfoResponse struct {
	System SystemInfo `json:"system"`
	Disk   DiskUsage  `json:"disk"`
}

// ContainerInfo is a summary of a container's state as returned by
// /api/v1/containers.
type ContainerInfo struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Image   string `json:"image"`
	State   string `json:"state"`
	Status  string `json:"status"`
	Created int64  `json:"created"`
}

// ContainerDetail is the raw JSON body returned by
// /api/v1/containers/{id}. BONNIE forwards Docker's InspectResponse shape;
// we expose it as json.RawMessage so callers can decode into whatever shape
// they need without coupling to docker/api/types/container.
type ContainerDetail struct {
	Raw json.RawMessage
}

// CreateContainerRequest describes a container to create on a BONNIE host.
type CreateContainerRequest struct {
	Name    string   `json:"name"`
	Image   string   `json:"image"`
	Env     []string `json:"env,omitempty"`
	Mounts  []string `json:"mounts,omitempty"`
	GPU     bool     `json:"gpu"`
	Command []string `json:"command,omitempty"`
}

// ExecRequest describes a command to execute on the host via /api/v1/exec.
type ExecRequest struct {
	Command string   `json:"command"`
	Args    []string `json:"args,omitempty"`
}

// ExecResult reports the exit code of a completed exec invocation. Output
// lines are delivered through the onLine callback while the stream is open.
type ExecResult struct {
	ExitCode int `json:"exit_code"`
}
