// osgb_engine.cpp — C++ 桥接层
// 基于官方 OpenSceneGraph 3.6.5 (Objexx VC2022 预编译包) + qslim GH 核心
// 功能: OSGB 目录 → 合并 → GH 简化(目标面数/四策略) → 写 FBX/OBJ/GLTF
// 注意: 必须最先 include windows.h, 定义 WINGDIAPI 等宏, OSG 的 <GL/gl.h> 依赖它
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <osg/Node>
#include <osg/Group>
#include <osg/Geode>
#include <osg/Geometry>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgUtil/Optimizer>
#include <osgDB/FileUtils>
#include <iostream>
#include <string>
#include <vector>
#include <cstdlib>
#include <cmath>
#include <filesystem>

#include "gh_simplify.hpp"

static void collectGeometry(osg::Node* node, std::vector<osg::ref_ptr<osg::Geometry>>& geoms)
{
    osg::Geode* geode = node->asGeode();
    if (geode) {
        for (unsigned i = 0; i < geode->getNumDrawables(); ++i) {
            osg::Geometry* geom = geode->getDrawable(i)->asGeometry();
            if (geom) geoms.push_back(geom);
        }
    }
    osg::Group* group = node->asGroup();
    if (group) {
        for (unsigned i = 0; i < group->getNumChildren(); ++i) {
            collectGeometry(group->getChild(i), geoms);
        }
    }
}

static unsigned countTriangles(osg::Node* node)
{
    std::vector<osg::ref_ptr<osg::Geometry>> geoms;
    collectGeometry(node, geoms);
    unsigned total = 0;
    for (auto& g : geoms) {
        osg::Geometry::PrimitiveSetList& prims = g->getPrimitiveSetList();
        for (auto& p : prims) {
            GLenum mode = p->getMode();
            if (mode == GL_TRIANGLES) total += p->getNumIndices() / 3;
            else if (mode == GL_TRIANGLE_STRIP || mode == GL_TRIANGLE_FAN) total += p->getNumIndices() - 2;
            else if (mode == GL_QUADS) total += p->getNumIndices() / 2;
            else if (mode == GL_POLYGON) total += p->getNumIndices() - 2;
        }
    }
    return total;
}

int main(int argc, char* argv[])
{
    // 用法: osgb_engine <input_dir> <output> [target_faces] [strategy] [method]
    //   input_dir: 含 metadata.xml + Data/ 的 OSGB 工程目录
    //   strategy:  0=triangular 1=prob_triangular 2=planar 3=prob_planar
    //   method:    gh (Garland-Heckbert) | lt (Lindstrom-Turk, 预留)
    if (argc < 3) {
        std::cerr << "Usage: osgb_engine <input_dir> <output> [target_faces] [strategy] [method]\n"
                  << "  strategy: 0=triangular 1=prob_triangular 2=planar 3=prob_planar\n"
                  << "  method:   gh|lt\n";
        return 1;
    }
    std::string inputDir = argv[1];
    std::string output = argv[2];
    int targetFaces = (argc > 3) ? std::atoi(argv[3]) : 0;
    int strategy = (argc > 4) ? std::atoi(argv[4]) : 0;
    std::string method = (argc > 5) ? argv[5] : "gh";

    osgDB::Registry::instance()->getDataFilePathList().push_back(inputDir);
    std::string dataDir = inputDir + "\\Data";

    // 1. 加载瓦片: 两种模式
    //    - input 含 Data/ 子目录 → 工程模式, 遍历所有 Tile_+XX_+YY 根瓦片
    //    - input 直接是瓦片目录(如 ...\Data\Tile_+034_+036) → 单瓦片模式
    osg::ref_ptr<osg::Group> merged = new osg::Group;
    unsigned tileCount = 0;
    if (std::filesystem::is_directory(dataDir)) {
        // 工程模式: 遍历 Data/ 下所有瓦片
        osgDB::Registry::instance()->getDataFilePathList().push_back(dataDir);
        try {
            for (const auto& entry : std::filesystem::directory_iterator(dataDir)) {
                if (!entry.is_directory()) continue;
                std::string tileDir = entry.path().string();
                std::string tileFile = tileDir + "\\" + entry.path().filename().string() + ".osgb";
                if (!std::filesystem::exists(tileFile)) continue;
                osg::ref_ptr<osg::Node> tile = osgDB::readNodeFile(tileFile);
                if (tile.valid()) {
                    merged->addChild(tile.get());
                    tileCount++;
                } else {
                    std::cerr << "Warning: failed to read " << tileFile << std::endl;
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "Directory iteration error: " << e.what() << std::endl;
        }
    } else {
        // 单瓦片模式: input 直接是瓦片目录
        std::string tileDir = inputDir;
        std::string tileFile = tileDir + "\\" + std::filesystem::path(inputDir).filename().string() + ".osgb";
        if (!std::filesystem::exists(tileFile)) {
            // 兜底: 目录里找第一个 .osgb(非 LOD 子瓦片)
            for (const auto& e2 : std::filesystem::directory_iterator(tileDir)) {
                if (e2.path().extension() == ".osgb" &&
                    e2.path().filename().string().find("_L") == std::string::npos) {
                    tileFile = e2.path().string();
                    break;
                }
            }
        }
        osg::ref_ptr<osg::Node> tile = osgDB::readNodeFile(tileFile);
        if (tile.valid()) {
            merged->addChild(tile.get());
            tileCount = 1;
        } else {
            std::cerr << "Failed to read single tile: " << tileFile << std::endl;
        }
    }

    if (tileCount == 0) {
        std::cerr << "Failed: no root tiles found under " << dataDir << std::endl;
        return 2;
    }
    osg::ref_ptr<osg::Node> root = merged;
    std::cout << "Loaded " << tileCount << " root tiles." << std::endl;

    unsigned before = countTriangles(root.get());
    std::cout << "Triangles before: " << before << std::endl;

    // 2. 合并: 展平静态变换 + 冗余节点清理(不合并几何, 保留各瓦片独立便于 GH 分块)
    osgUtil::Optimizer optimizer;
    optimizer.optimize(root.get(),
        osgUtil::Optimizer::FLATTEN_STATIC_TRANSFORMS |
        osgUtil::Optimizer::REMOVE_REDUNDANT_NODES |
        osgUtil::Optimizer::COMBINE_ADJACENT_LODS);

    // 3. GH 简化: 遍历所有 Geometry, 每个执行边折叠到目标面数
    //    目标面数按总面积比例分配到各 Geometry
    if (targetFaces > 0 && before > 0) {
        std::vector<osg::ref_ptr<osg::Geometry>> geoms;
        collectGeometry(root.get(), geoms);
        unsigned totalGeom = 0;
        for (auto& g : geoms) {
            osg::Geometry::PrimitiveSetList& prims = g->getPrimitiveSetList();
            for (auto& p : prims) {
                GLenum mode = p->getMode();
                if (mode == GL_TRIANGLES) totalGeom += p->getNumIndices() / 3;
                else if (mode == GL_TRIANGLE_STRIP || mode == GL_TRIANGLE_FAN) totalGeom += p->getNumIndices() - 2;
                else if (mode == GL_QUADS) totalGeom += p->getNumIndices() / 2;
            }
        }
        std::cout << "Geometry blocks: " << geoms.size() << ", total faces " << totalGeom << std::endl;
        for (auto& g : geoms) {
            unsigned gf = 0;
            osg::Geometry::PrimitiveSetList& prims = g->getPrimitiveSetList();
            for (auto& p : prims) {
                GLenum mode = p->getMode();
                if (mode == GL_TRIANGLES) gf += p->getNumIndices() / 3;
                else if (mode == GL_TRIANGLE_STRIP || mode == GL_TRIANGLE_FAN) gf += p->getNumIndices() - 2;
                else if (mode == GL_QUADS) gf += p->getNumIndices() / 2;
            }
            int gt = (gf > 0) ? (int)((double)targetFaces * (double)gf / (double)totalGeom) : 0;
            if (gt >= 4 && gt < (int)gf) {
                unsigned gb = gf;
                gh_simplify_geometry(g.get(), gt, strategy);
                // GH 之后重新统计面数
                unsigned gaf = 0;
                osg::Geometry::PrimitiveSetList& aprims = g->getPrimitiveSetList();
                for (auto& p : aprims) {
                    GLenum amode = p->getMode();
                    if (amode == GL_TRIANGLES) gaf += p->getNumIndices() / 3;
                    else if (amode == GL_TRIANGLE_STRIP || amode == GL_TRIANGLE_FAN) gaf += p->getNumIndices() - 2;
                    else if (amode == GL_QUADS) gaf += p->getNumIndices() / 2;
                }
                std::cout << "  geom: " << gb << " -> " << gaf << " (target " << gt << ")" << std::endl;
            }
        }
    }

    unsigned after = countTriangles(root.get());
    std::cout << "Triangles after: " << after << std::endl;

    // 4. 写输出(按扩展名: .fbx / .obj / .gltf / .osgb)
    if (!osgDB::writeNodeFile(*root, output)) {
        std::cerr << "Failed to write: " << output << std::endl;
        return 3;
    }
    std::cout << "Written: " << output << std::endl;
    return 0;
}
