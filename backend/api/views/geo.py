"""Map link / coordinates preview for the panel's location field."""

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ServiceError
from core.geo import coord_str, location_input, yandex_url

from ..permissions import IsStaffUser


class GeoParseSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, max_length=2000)


class GeoParseView(APIView):
    """POST {text} -> {lat, lon, map_url, short}; 400 {location} when unreadable.
    No database, no network: a short link is reported (`short`) but not resolved."""

    permission_classes = [IsStaffUser]
    serializer_class = GeoParseSerializer

    def post(self, request):
        body = GeoParseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            point, link, short = location_input(body.validated_data["text"])
        except ServiceError as e:
            return Response({"location": e.message}, status=400)
        return Response(
            {
                "lat": coord_str(point.lat) if point else None,
                "lon": coord_str(point.lon) if point else None,
                "map_url": yandex_url(point.lat, point.lon, link=link or "") if point else link,
                "short": short,
            }
        )
