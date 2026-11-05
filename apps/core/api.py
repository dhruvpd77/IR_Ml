from django.db.models import Q
from rest_framework import serializers, viewsets

from machines.models import Machine
from machines.services import visible_machines


class MachineSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source="planning.company", read_only=True)
    work_order = serializers.CharField(source="planning.work_order", read_only=True)
    ccn = serializers.CharField(source="planning.ccn", read_only=True)
    model_description = serializers.CharField(source="planning.model_description", read_only=True)
    status_label = serializers.CharField(read_only=True)
    station_name = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [
            "machine_id",
            "status",
            "status_label",
            "current_phase",
            "priority",
            "planner_serial",
            "production_serial",
            "company",
            "work_order",
            "ccn",
            "model_description",
            "station_name",
            "is_under_rework",
            "rework_count",
            "created_at",
            "updated_at",
            "qc_approved_at",
        ]

    def get_station_name(self, obj):
        return obj.station.name if obj.station_id else ""


class MachineViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MachineSerializer
    lookup_field = "machine_id"

    def get_queryset(self):
        queryset = visible_machines(self.request.user).select_related("planning", "station")
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params.get("status"))
        if params.get("priority"):
            queryset = queryset.filter(priority=params.get("priority"))
        query = (params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(machine_id__icontains=query)
                | Q(planning__work_order__icontains=query)
                | Q(planner_serial__icontains=query)
                | Q(planning__model_description__icontains=query)
            )
        return queryset
