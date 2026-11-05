from django.contrib import admin

from machines.models import ImportBatch, Machine, MachinePlanningData, PlanningCatalogItem, ProductionStation

admin.site.register(ProductionStation)
admin.site.register(MachinePlanningData)
admin.site.register(ImportBatch)


@admin.register(PlanningCatalogItem)
class PlanningCatalogItemAdmin(admin.ModelAdmin):
    list_display = ("company", "machine_type", "model_description", "ccn", "uploaded_at")
    search_fields = ("company", "machine_type", "model_description", "ccn")
    list_filter = ("company", "machine_type")


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("machine_id", "status", "current_phase", "priority", "planner_serial", "created_at")
    search_fields = ("machine_id", "planner_serial", "production_serial")
    readonly_fields = (
        "machine_id",
        "status",
        "current_phase",
        "planner_serial",
        "production_serial",
        "is_under_rework",
        "rework_count",
        "qc_approved_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False
