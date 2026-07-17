package featuregate

type Gate string

const (
	Registry   Gate = "registry"
	AutoUpdate Gate = "auto-update"
)

type Gates struct {
	registryEnabled   bool
	autoUpdateEnabled bool
}

func New(registryEnabled, autoUpdateEnabled bool) Gates {
	return Gates{registryEnabled: registryEnabled, autoUpdateEnabled: autoUpdateEnabled}
}

func (g Gates) Enabled(gate Gate) bool {
	switch gate {
	case Registry:
		return g.registryEnabled
	case AutoUpdate:
		return g.registryEnabled && g.autoUpdateEnabled
	default:
		return false
	}
}
