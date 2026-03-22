from pydantic import BaseModel


class PortResponse(BaseModel):
    port_id: int
    port_code: str
    port_name: str
    country_code: str | None = None
    zone_code: str | None = None
    is_eu_port: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None
