import { createFileRoute } from "@tanstack/react-router";
import IntegratedDashboard from "@/components/IntegratedDashboard";

export const Route = createFileRoute("/")({
  component: IntegratedDashboard,
  head: () => ({
    meta: [
      { title: "Autonomous Truck Dumping Optimisation · Caterpillar Demo" },
      {
        name: "description",
        content:
          "Interactive LiDAR-guided autonomous truck dumping simulation for mine sites. Columnar dump strategy with slope-critical saddle detection.",
      },
    ],
  }),
});
