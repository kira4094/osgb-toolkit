// osgb_simplify.cpp — 用 osgUtil::Simplifier(GH/QEM)简化 OBJ
// 对齐 OPEditor: 先合并顶点, 再用 OSG QEM 简化(不保边界)
// 用法: osgb_simplify <in.obj> <out.obj> <target_faces> <planar>
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
#include <osgUtil/Simplifier>
#include <osgUtil/Optimizer>
#include <iostream>
#include <string>
#include <cstdlib>

// 收集所有 Geometry 并统计
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
        for (unsigned i = 0; i < group->getNumChildren(); ++i)
            collectGeometry(group->getChild(i), geoms);
    }
}

static unsigned countTriangles(osg::Node* node)
{
    std::vector<osg::ref_ptr<osg::Geometry>> geoms;
    collectGeometry(node, geoms);
    unsigned total = 0;
    for (auto& g : geoms) {
        for (auto& p : g->getPrimitiveSetList()) {
            GLenum mode = p->getMode();
            if (mode == GL_TRIANGLES) total += p->getNumIndices() / 3;
            else if (mode == GL_TRIANGLE_STRIP || mode == GL_TRIANGLE_FAN) total += p->getNumIndices() - 2;
            else if (mode == GL_QUADS) total += p->getNumIndices() / 2;
        }
    }
    return total;
}

int main(int argc, char* argv[])
{
    if (argc < 4) {
        std::cerr << "Usage: osgb_simplify <in.obj> <out.obj> <target_faces> [planar]\n"
                  << "  planar: 1=平面策略 0=三角形策略\n";
        return 1;
    }
    std::string input = argv[1];
    std::string output = argv[2];
    unsigned targetFaces = std::atoi(argv[3]);
    bool planar = (argc > 4) ? (std::atoi(argv[4]) == 1) : false;

    // 设置插件路径(OBJ 读取)
    const char* osg_lib = std::getenv("OSG_LIBRARY_PATH");
    if (osg_lib) osgDB::Registry::instance()->setLibraryFilePathList(osg_lib);

    osg::ref_ptr<osg::Node> root = osgDB::readNodeFile(input);
    if (!root.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }

    unsigned before = countTriangles(root.get());
    std::cout << "Triangles before: " << before << std::endl;

    // 用 osgUtil::Simplifier(GH/QEM)
    double sampleRatio = (double)targetFaces / (double)before;
    if (sampleRatio > 1.0) sampleRatio = 1.0;
    // 平面策略: 高误差容忍 + 更激进采样; 三角形: 严格
    double maxError = planar ? 1e-3 : 1e-8;
    double maxLength = 0.0;
    if (planar) sampleRatio *= 0.8;  // 平面策略更激进

    osgUtil::Simplifier simplifier(sampleRatio, maxError, maxLength);
    // 关键: 不保边界(和 OPEditor 一样, 边界由独立缝合步骤处理)
    simplifier.setDoTriStrip(false);
    root->accept(simplifier);

    unsigned after = countTriangles(root.get());
    std::cout << "Simplified (ratio=" << sampleRatio << ", planar=" << planar << "): "
              << before << " -> " << after << " triangles" << std::endl;

    if (!osgDB::writeNodeFile(*root, output)) {
        std::cerr << "Failed to write: " << output << std::endl;
        return 3;
    }
    std::cout << "Written: " << output << std::endl;
    return 0;
}
