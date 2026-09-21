from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.models import Device
from .models import InstalledApp, UsageSession
from .serializers import (
    InstalledAppSerializer,
    UsageSessionSerializer,
    UsageSyncRequestSerializer,
)


class AppListView(generics.ListAPIView):
    serializer_class = InstalledAppSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user_devices = Device.objects.filter(user=self.request.user)
        return InstalledApp.objects.filter(device__in=user_devices).order_by('app_name')


class AppDetailView(generics.RetrieveAPIView):
    serializer_class = InstalledAppSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user_devices = Device.objects.filter(user=self.request.user)
        return InstalledApp.objects.filter(device__in=user_devices)


class AppHistoryView(generics.ListAPIView):
    serializer_class = UsageSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user_devices = Device.objects.filter(user=self.request.user)
        qs = UsageSession.objects.filter(installed_app__device__in=user_devices)

        app_id = self.kwargs.get('pk')
        if app_id:
            qs = qs.filter(installed_app_id=app_id)

        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(start_time__date__gte=date_from)
        if date_to:
            qs = qs.filter(start_time__date__lte=date_to)

        return qs.order_by('-start_time')


class UsageSyncView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = UsageSyncRequestSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data['device_id']
        sessions_data = serializer.validated_data['sessions']

        device = Device.objects.get(id=device_id)
        device.last_sync_at = timezone.now()
        device.save(update_fields=['last_sync_at'])

        created_count = 0
        duplicate_count = 0
        invalid_count = 0

        for session_data in sessions_data:
            try:
                installed_app, _ = InstalledApp.objects.get_or_create(
                    device=device,
                    package_name=session_data['package_name'],
                    defaults={
                        'app_name': session_data.get('app_name', ''),
                    },
                )

                if session_data.get('app_name') and installed_app.app_name != session_data['app_name']:
                    installed_app.app_name = session_data['app_name']
                    installed_app.save(update_fields=['app_name'])

                exists = UsageSession.objects.filter(
                    device=device,
                    package_name=session_data['package_name'],
                    start_time=session_data['start_time'],
                    end_time=session_data['end_time'],
                ).exists()

                if exists:
                    duplicate_count += 1
                    continue

                UsageSession.objects.create(
                    device=device,
                    installed_app=installed_app,
                    package_name=session_data['package_name'],
                    start_time=session_data['start_time'],
                    end_time=session_data['end_time'],
                    duration_seconds=session_data['duration_seconds'],
                    source='system',
                )
                created_count += 1

                if (
                    installed_app.last_opened_at is None
                    or session_data['start_time'] > installed_app.last_opened_at
                ):
                    installed_app.last_opened_at = session_data['start_time']
                    installed_app.save(update_fields=['last_opened_at'])

            except Exception:
                invalid_count += 1

        return Response({
            'created': created_count,
            'duplicates': duplicate_count,
            'invalid': invalid_count,
        }, status=status.HTTP_201_CREATED)


class ActivityView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        date_str = request.query_params.get('date')
        device_id = request.query_params.get('device_id')

        if not date_str:
            return Response(
                {'error': 'date parameter is required (YYYY-MM-DD)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from datetime import date as date_type
            query_date = date_type.fromisoformat(date_str)
        except ValueError:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_devices = Device.objects.filter(user=request.user)
        if device_id:
            user_devices = user_devices.filter(id=device_id)

        sessions = UsageSession.objects.filter(
            device__in=user_devices,
            start_time__date=query_date,
        ).select_related('installed_app').order_by('-start_time')

        session_list = []
        for s in sessions:
            session_list.append({
                'id': str(s.id),
                'app_name': s.installed_app.app_name if s.installed_app else s.package_name,
                'package_name': s.package_name,
                'start_time': s.start_time.isoformat(),
                'end_time': s.end_time.isoformat(),
                'duration_seconds': s.duration_seconds,
            })

        return Response({
            'date': query_date.isoformat(),
            'sessions': session_list,
        })


class ReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        report_type = request.query_params.get('type')
        date_param = request.query_params.get('date')
        fmt = request.query_params.get('format', 'csv')

        if report_type not in ('daily', 'monthly'):
            return Response(
                {'error': 'type parameter is required (daily or monthly)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not date_param:
            return Response(
                {'error': 'date parameter is required (YYYY-MM-DD for daily, YYYY-MM for monthly)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_devices = Device.objects.filter(user=request.user)

        try:
            if report_type == 'daily':
                from datetime import date as date_type
                query_date = date_type.fromisoformat(date_param)
                sessions = UsageSession.objects.filter(
                    device__in=user_devices,
                    start_time__date=query_date,
                ).select_related('installed_app').order_by('-start_time')
            else:
                parts = date_param.split('-')
                year = int(parts[0])
                month = int(parts[1])
                sessions = UsageSession.objects.filter(
                    device__in=user_devices,
                    start_time__year=year,
                    start_time__month=month,
                ).select_related('installed_app').order_by('-start_time')
        except (ValueError, IndexError):
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD for daily or YYYY-MM for monthly.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fmt == 'json':
            session_list = []
            total_seconds = 0
            unique_packages = set()
            for s in sessions:
                duration_min = round(s.duration_seconds / 60, 1)
                total_seconds += s.duration_seconds
                pkg = s.package_name
                unique_packages.add(pkg)
                session_list.append({
                    'app_name': s.installed_app.app_name if s.installed_app else pkg,
                    'package_name': pkg,
                    'start_time': s.start_time.isoformat(),
                    'end_time': s.end_time.isoformat(),
                    'duration_seconds': s.duration_seconds,
                    'duration_minutes': duration_min,
                    'source': s.source,
                })

            return Response({
                'report_type': report_type,
                'date': date_param,
                'total_sessions': len(session_list),
                'total_duration_seconds': total_seconds,
                'total_duration_minutes': round(total_seconds / 60, 1),
                'unique_apps': len(unique_packages),
                'sessions': session_list,
            })

        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'App Name', 'Package Name', 'Start Time', 'End Time',
            'Duration (seconds)', 'Duration (minutes)', 'Source',
        ])

        total_seconds = 0
        for s in sessions:
            duration_min = round(s.duration_seconds / 60, 1)
            total_seconds += s.duration_seconds
            writer.writerow([
                s.installed_app.app_name if s.installed_app else s.package_name,
                s.package_name,
                s.start_time.isoformat(),
                s.end_time.isoformat(),
                s.duration_seconds,
                duration_min,
                s.source,
            ])

        writer.writerow([])
        writer.writerow(['Total Sessions', sessions.count()])
        writer.writerow(['Total Duration (seconds)', total_seconds])
        writer.writerow(['Total Duration (minutes)', round(total_seconds / 60, 1)])

        csv_content = output.getvalue()
        output.close()

        filename = f"orbit-report-{date_param}.csv"
        response = HttpResponse(csv_content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
