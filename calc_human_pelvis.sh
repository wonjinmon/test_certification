python calc_humans.py --bg_pcd_path ./data/test0.pcd --human_pcd_path ./data/test1.pcd --out_pcd_path ./data/result/test_result1.pcd
python calc_upperbody.py --human_pcd_path ./data/test_result1.pcd



python patch_bvh_angles.py ./BVH/input.bvh --Hips --RightCollar --RightShoulder --RightElbow --RightWrist
python endSite.py ./BVH/input_patched.bvh
python L2distance_with_csv.py ./BVH/input_patched.bvh