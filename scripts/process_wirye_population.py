import os
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# 1. 위례동(창곡동) 경계 로드 (EPSG:4326 -> EPSG:5179 변환)
boundary_path = 'data/processed/wirye_changgok_boundary.geojson'
boundary = gpd.read_file(boundary_path)
boundary_5179 = boundary.to_crs(epsg=5179)
wirye_geom = boundary_5179.geometry.iloc[0]

# 2. 바운딩 박스를 이용한 100M 격자 로드
minx, miny, maxx, maxy = boundary_5179.total_bounds
grid_shp_path = 'data/raw/_grid_border_grid_2025_grid_다사_grid_다사 (1)/grid_다사_100M.shp'
grid_gdf = gpd.read_file(grid_shp_path, bbox=(minx, miny, maxx, maxy))

# 3. 위례동 경계 내부에 중심점(Centroid)이 위치하는 격자 추출 (표준 공간 통계 기준)
grid_gdf['centroid_5179'] = grid_gdf.geometry.centroid
within_mask = grid_gdf['centroid_5179'].within(wirye_geom)
wirye_grids = grid_gdf[within_mask].copy()

# 중심점의 WGS84 (경도, 위도) 좌표 계산
centroid_gdf = gpd.GeoDataFrame(wirye_grids[['GRID_CD']], geometry=wirye_grids['centroid_5179'], crs=5179)
centroid_4326 = centroid_gdf.to_crs(epsg=4326)

wirye_grids['중심_X_5179'] = wirye_grids['centroid_5179'].x.round(2)
wirye_grids['중심_Y_5179'] = wirye_grids['centroid_5179'].y.round(2)
wirye_grids['중심_경도'] = centroid_4326.geometry.x.round(7)
wirye_grids['중심_위도'] = centroid_4326.geometry.y.round(7)

# 4. 인구 통계 데이터 로드 (2024년 총인구 to_in_001)
census_csv_path = 'data/raw/_census_reqdoc_1791098813447/2024년_인구_다사_100M.csv'
pop_df = pd.read_csv(census_csv_path, encoding='cp949', header=None)
pop_df.columns = ['year', 'GRID_CD', 'item_cd', 'value']

# 총인구(to_in_001) 필터링
pop_total = pop_df[pop_df['item_cd'] == 'to_in_001'][['GRID_CD', 'value']]
pop_total.rename(columns={'value': '인구'}, inplace=True)

# 5. 병합 (인구가 없는 격자는 0으로 처리)
merged = wirye_grids.merge(pop_total, on='GRID_CD', how='left')
merged['인구'] = merged['인구'].fillna(0).astype(int)

# 6. 컬럼 정리 및 정렬
result_df = merged[['GRID_CD', '인구', '중심_경도', '중심_위도', '중심_X_5179', '중심_Y_5179']].copy()
result_df.rename(columns={'GRID_CD': '격자ID'}, inplace=True)
result_df.sort_values(by=['인구', '격자ID'], ascending=[False, True], inplace=True)

# 7. CSV 저장 (UTF-8 BOM)
os.makedirs('data/processed', exist_ok=True)
out_csv = 'data/processed/wirye_grid_population.csv'
result_df.to_csv(out_csv, index=False, encoding='utf-8-sig')

total_pop = result_df['인구'].sum()
populated_grids = (result_df['인구'] > 0).sum()
total_grids = len(result_df)

print(f"저장 완료: {out_csv}")
print(f"총 격자 수: {total_grids}개")
print(f"인구 거주 격자 수: {populated_grids}개")
print(f"위례동 총 격자 인구 합계: {total_pop:,}명")
print("\n[상위 5개 격자]")
print(result_df.head(5).to_string(index=False))
