import Config

config :shout, enabled: false

config :pleroma, :frontend_configurations,
  pleroma_fe: %{
    theme: "pleroma-light",
    redirectRootNoLogin: "/hello"
}
